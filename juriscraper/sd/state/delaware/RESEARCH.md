# Delaware Courts Research

## Court Structure

Delaware has a unique court system with several courts, but notably **no intermediate appellate court**. Appeals from trial courts go directly to the Supreme Court.

### 1. Supreme Court of Delaware
- **Website**: https://courts.delaware.gov/supreme/
- Highest court in Delaware
- 1 Chief Justice + 4 Justices (5 total)
- Justices serve 12-year terms
- Three justices must be from one major political party, two from the other
- Final appellate jurisdiction in criminal cases (where sentence exceeds certain minimums)
- Appellate jurisdiction over Court of Chancery, Superior Court, and Family Court
- Discretionary jurisdiction for writs of prohibition, quo warranto, certiorari, mandamus
- Location: Delaware Supreme Court Building, Dover (temporarily at Kent County Courthouse during renovations)

### 2. Court of Chancery
- **Website**: https://courts.delaware.gov/chancery/
- **Nationally famous** for corporate and business law
- Non-jury trial court with exclusive equity jurisdiction
- 1 Chancellor + 6 Vice Chancellors + 7 Magistrates in Chancery
- Chancellor and Vice Chancellors serve 12-year terms
- Jurisdiction: trusts, real property, guardianships, civil rights, commercial litigation
- Appeals go directly to Supreme Court

### 3. Superior Court
- **Website**: https://courts.delaware.gov/superior/
- Court of general jurisdiction
- Handles felony criminal cases and major civil cases
- Appeals go directly to Supreme Court

### 4. Family Court
- **Website**: https://courts.delaware.gov/family/
- Handles family and juvenile matters
- Appeals go directly to Supreme Court

### 5. Court of Common Pleas
- **Website**: https://courts.delaware.gov/commonpleas/
- Limited jurisdiction court
- Civil cases up to $75,000
- Certain criminal matters

### 6. Justice of the Peace Court
- **Website**: https://courts.delaware.gov/jpcourt/
- Limited jurisdiction
- Civil cases up to $25,000
- Minor criminal matters

---

## Key URLs and URL Patterns

### Main Portal
- **Delaware Courts**: https://courts.delaware.gov/

### Opinions Database
- **Main Opinions Page**: https://courts.delaware.gov/opinions/
- **Supreme Court Opinions**: https://courts.delaware.gov/opinions/index.aspx?ag=supreme+court
- **Court of Chancery Opinions**: https://courts.delaware.gov/opinions/index.aspx?ag=court%20of%20chancery
- **Superior Court Opinions**: https://courts.delaware.gov/opinions/index.aspx?ag=superior+court

### Opinion Download Pattern
- **Download URL**: `https://courts.delaware.gov/Opinions/Download.aspx?id={opinion_id}`
- Example: `https://courts.delaware.gov/Opinions/Download.aspx?id=390230`
- Downloads PDF directly (no intermediate detail page)

### Opinions Search Parameters
The opinions page at `/opinions/` supports filtering by:
- **Court**: All Courts, Court of Chancery, Court of Common Pleas, Family Court, Justice Of The Peace Court, Superior Court, Supreme Court
- **Revision Date**: Past 7 days, Past 30 days, Past 180 days, This year, Custom year, Custom dates
- **Search**: Free text search
- **Case Type Tabs**: All Cases, Civil, Criminal, Complex Commercial Litigation Division

### Oral Arguments
- **Supreme Court Oral Arguments**: https://courts.delaware.gov/supreme/oralarguments/
- Live streaming and recorded proceedings available

### Civil Case Search (Docket)
- **CourtConnect Portal**: https://courtconnect.courts.delaware.gov/cc/cconnect/ck_public_qry_main.cp_main_idx
- Covers Superior Court, Court of Common Pleas, and Justice of the Peace Court
- Search by name, business name, case type, or judgments
- Note: Court of Chancery dockets are on File & ServeXpress (http://www.fileandservexpress.com/)

### Case Number Patterns

| Court | Pattern | Example |
|-------|---------|---------|
| Supreme Court | {seq}, {year} | 340, 2024 |
| Court of Chancery | C.A. No. {year}-{seq}-{judge initials} | C.A. No. 2024-1022-BWD |
| Court of Chancery (alt) | {year}-{seq}-{judge initials} | 2025-0975-LWW |
| Superior Court (Civil) | {county}{year}C-{month}-{seq} {judge initials} | S24C-02-038 MHC |
| Superior Court (Criminal) | {year}{county code}{seq} | 2505004443 |

County codes:
- N = New Castle County
- K = Kent County
- S = Sussex County

Judge initials appear at end of case numbers (e.g., BWD = Bonnie W. David, V.C.)

---

## Current Justices - Supreme Court

### Chief Justice
| Name | Title | Appointed | Bio URL |
|------|-------|-----------|---------|
| Collins J. Seitz, Jr. | Chief Justice | 2015 (Justice), Nov 8, 2019 (Chief) | https://courts.delaware.gov/supreme/justices.aspx |

### Associate Justices
| Name | Appointed | Notes | Bio URL |
|------|-----------|-------|---------|
| Karen L. Valihura | July 25, 2014 | Stepping down July 2026 | https://courts.delaware.gov/supreme/justices.aspx |
| Gary F. Traynor | July 5, 2017 | | https://courts.delaware.gov/supreme/justices.aspx |
| Abigail M. LeGrow | May 11, 2023 | Former Superior Court Judge | https://courts.delaware.gov/supreme/justices.aspx |
| N. Christopher Griffiths | May 22, 2023 | | https://courts.delaware.gov/supreme/justices.aspx |

---

## Current Judicial Officers - Court of Chancery

### Chancellor
| Name | Appointed | Bio URL |
|------|-----------|---------|
| Kathaleen St. J. McCormick | May 6, 2021 (Chancellor), Nov 1, 2018 (Vice Chancellor) | https://courts.delaware.gov/chancery/judges.aspx |

### Vice Chancellors
| Name | Bio URL |
|------|---------|
| J. Travis Laster | https://courts.delaware.gov/chancery/judges.aspx |
| Morgan T. Zurn | https://courts.delaware.gov/chancery/judges.aspx |
| Paul A. Fioravanti, Jr. | https://courts.delaware.gov/chancery/judges.aspx |
| Lori W. Will | https://courts.delaware.gov/chancery/judges.aspx |
| Nathan A. Cook | https://courts.delaware.gov/chancery/judges.aspx |
| Bonnie W. David | https://courts.delaware.gov/chancery/judges.aspx |

### Magistrates in Chancery
| Name | Notes | Bio URL |
|------|-------|---------|
| Selena E. Molina | Senior Magistrate, leaving Feb 28, 2026 | https://courts.delaware.gov/chancery/judges.aspx |
| Loren Mitchell | | https://courts.delaware.gov/chancery/judges.aspx |
| Christian Douglas Wright | | https://courts.delaware.gov/chancery/judges.aspx |
| Danielle Gibbs | | https://courts.delaware.gov/chancery/judges.aspx |
| David Hume, IV | | https://courts.delaware.gov/chancery/judges.aspx |
| Brittingham | | https://courts.delaware.gov/chancery/judges.aspx |
| Benavides | | https://courts.delaware.gov/chancery/judges.aspx |

### Active Retired Judicial Officers
| Name | Bio URL |
|------|---------|
| Sam Glasscock III (Vice Chancellor, retired 2025) | https://courts.delaware.gov/chancery/judges.aspx |
| Patricia W. Griffin (Magistrate, retired) | https://courts.delaware.gov/chancery/judges.aspx |

---

## Opinion Types and Publication

### Supreme Court
- Opinions and Orders published on opinions page
- PDF download via `/Opinions/Download.aspx?id={id}`
- Shows originating court in parentheses: "Supreme Court (Court of Chancery)", "Supreme Court (Superior Court)", etc.

### Court of Chancery
- Famous for corporate law opinions
- Multiple opinion types: Opinion, Memorandum Opinion, Letter Opinion, Letter Decision, Order
- Vice Chancellors identified by initials in case numbers

### All Courts
- Available document types: Opinion, Order, Memorandum Opinion, Letter Opinion, Letter Decision, Post-Trial Opinion
- Judicial officer title abbreviations:
  - C. = Chancellor or Commissioner
  - C.J. = Chief Justice or Chief Judge
  - J. = Justice or Judge
  - S.M. = Senior Magistrate
  - M. = Magistrate in Chancery
  - P.J. = President Judge
  - R.J. = Resident Judge
  - V.C. = Vice Chancellor

---

## Access Restrictions

### No Login Required
- All opinion PDFs publicly accessible via Download.aspx
- Opinions database searchable without authentication
- No rate limiting observed during research

### Login Required
- Court of Chancery eFiling via File & ServeXpress (attorneys only)
- CourtConnect for detailed civil case dockets (free registration may be required)

### Data Availability
- Opinions searchable by date range: past 7 days, 30 days, 180 days, this year, custom
- Historical opinions available through the search interface
- Oral arguments available via streaming/recording

---

## Technical Implementation Notes

### Website Platform
- ASP.NET-based website (.aspx pages)
- Modern responsive design
- JavaScript-heavy UI with tabbed interfaces

### Opinions Page Architecture
- Single unified opinions page for all courts
- Dynamic filtering via dropdown selections
- Tabbed interface for case types (Civil/Criminal/CCLD)
- Pagination with configurable results per page (25, 50, 100)
- Sortable columns: Parties/Caption, Date, File Number, Court, Type, Judicial Officer
- Opinion download is direct PDF via Download.aspx with ID parameter

### API/Data Access
- No public API identified
- Web scraping required for most data
- Opinions page returns structured table data suitable for parsing

### Scraping Considerations
- Opinion IDs are numeric (e.g., 390230)
- Download URL pattern is consistent: `/Opinions/Download.aspx?id={id}`
- Court filter values match court names exactly
- Date filters use predefined ranges or custom date selection

---

## Example Cases

### Supreme Court
- **340, 2024** - Moelis & Company v. West Palm Beach Firefighters' Pension Fund (Jan 20, 2026)
  - Download: https://courts.delaware.gov/Opinions/Download.aspx?id=390230
  - Appeal from Court of Chancery
  - Justice: Traynor J.

- **392, 2023** - Suber v. State (Jan 15, 2026)
  - Appeal from Superior Court
  - Criminal case
  - Chief Justice: Seitz C.J.

### Court of Chancery
- **C.A. No. 2024-1022-BWD** - Andrea Benson v. Chad Huggins (Jan 21, 2026)
  - Vice Chancellor: David, Bonnie W. V.C.
  - Type: Post-Trial Memorandum Opinion

- **C.A. No. 2025-0197-KSJM** - Flex Ltd., et al. v. Nextracker Inc., et al. (Jan 21, 2026)
  - Chancellor: McCormick, C.
  - Type: Memorandum Opinion

---

## Recommended Scraper Architecture

### Opinion Scraper (Primary)
1. **Source**: https://courts.delaware.gov/opinions/
2. **Approach**:
   - Query opinions page with court filter and date range
   - Parse HTML table for case metadata
   - Extract opinion ID from download button
   - Download PDFs via `/Opinions/Download.aspx?id={id}`
3. **Data Available**:
   - Parties/Caption
   - Date
   - File Number (case number)
   - Court (with originating court for Supreme Court appeals)
   - Type (Civil/Criminal)
   - Judicial Officer
   - Description (opinion type)

### Court-Specific Scrapers
Consider separate scrapers for:
1. **Supreme Court** - Highest priority for appellate opinions
2. **Court of Chancery** - High value for corporate law opinions
3. **Superior Court** - General jurisdiction matters

### Oral Arguments Scraper
1. **Source**: https://courts.delaware.gov/supreme/oralarguments/
2. **Approach**: Extract video links and case metadata
3. **Note**: Page is very large, may need pagination handling

### Considerations
- Delaware has no intermediate appellate court, so Supreme Court handles all appeals
- Court of Chancery is especially valuable due to corporate law prominence
- Opinion IDs appear to be sequential integers
- Multiple opinion types per case possible (Orders, Memorandum Opinions, etc.)
