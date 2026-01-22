# Rhode Island Courts Research

## Court Structure

Rhode Island has a unified judicial system with six courts, including one appellate court:

### 1. Supreme Court of Rhode Island
- **Website**: https://www.courts.ri.gov/Courts/SupremeCourt/Pages/default.aspx
- Highest and only appellate court in Rhode Island
- 5 Justices (1 Chief Justice + 4 Associate Justices)
- Justices are appointed by the Governor with the advice and consent of the Senate
- Justices serve for life during good behavior
- Located at the Frank J. Licht Judicial Complex, 250 Benefit Street, Providence

#### Jurisdiction
- Absolute appellate jurisdiction over questions of law and equity
- Supervisory powers over all other state courts
- General advisory responsibility to Legislative and Executive branches on constitutionality
- Regulates admission to the Rhode Island Bar
- Disciplines bar members
- No intermediate appellate court - appeals go directly from trial courts to Supreme Court

### 2. Superior Court (Trial Court)
- **Website**: https://www.courts.ri.gov/Courts/superiorcourt/Pages/default.aspx
- 22 Judges and 5 Magistrates
- General jurisdiction trial court for jury and non-jury trials
- Original jurisdiction in felony proceedings
- Civil cases where amount in controversy exceeds $10,000
- Equity matters
- Hears appeals de novo from District Court

### 3. Family Court (Trial Court)
- **Website**: https://www.courts.ri.gov/Courts/familycourt/Pages/default.aspx
- Handles domestic relations and juvenile matters

### 4. District Court (Trial Court)
- **Website**: https://www.courts.ri.gov/Courts/districtcourt/Pages/default.aspx
- Limited jurisdiction trial court
- Misdemeanors and civil cases under $10,000

### 5. Workers' Compensation Court
- **Website**: https://www.courts.ri.gov/Courts/workerscompensationcourt/Pages/default.aspx
- Specialized court for workers' compensation matters

### 6. Rhode Island Traffic Tribunal
- **Website**: https://www.courts.ri.gov/Courts/traffictribunal/Pages/default.aspx
- Handles most traffic cases
- Located at 670 New London Avenue, Cranston

---

## Key URLs and URL Patterns

### Main Portal
- **Rhode Island Judiciary Home**: https://www.courts.ri.gov/
- **Courts Overview**: https://www.courts.ri.gov/Courts/Pages/default.aspx
- **Supreme Court**: https://www.courts.ri.gov/Courts/SupremeCourt/Pages/default.aspx
- **Superior Court**: https://www.courts.ri.gov/Courts/superiorcourt/Pages/default.aspx

### Opinion Pages
- **Published Opinions (Supreme Court)**: https://www.courts.ri.gov/Courts/SupremeCourt/Pages/published-opinions.aspx
- **Opinions, Decisions, and Orders (All Courts)**: https://www.courts.ri.gov/Pages/ood.aspx

### Case Management System (Public Portal)
- **Portal Home**: https://publicportal.courts.ri.gov/PublicPortal
- **Smart Search**: https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/29
- **Search Hearings**: https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/26
- **Attorney/Agency Login**: https://publicportal.courts.ri.gov/publicportal/account/login

### Court Rules and Legal Resources
- **Court Rules Overview**: https://www.courts.ri.gov/Legal-Resources/Pages/court-rules.aspx
- **Supreme Court Rules**: https://www.courts.ri.gov/Legal-Resources/Pages/Supreme-Court-Rules.aspx
- **Superior Court Rules**: https://www.courts.ri.gov/Legal-Resources/Pages/Superior-Court-Rules.aspx
- **Rules of Evidence**: https://www.courts.ri.gov/Legal-Resources/Documents/RulesOfEvidence.pdf

### Oral Arguments / Calendar
- **Supreme Court Calendar Page**: https://www.courts.ri.gov/Pages/public-access-supreme.aspx
- **Hearing Dates PDF**: https://www.courts.ri.gov/Courts/SupremeCourt/Documents/Hearing_Dates.pdf
- **Monthly Oral Argument Calendar PDF**: https://www.courts.ri.gov/Courts/SupremeCourt/Documents/Oral_Argument_Calendar.pdf
- **Livestream (Dacast)**: https://iframe.dacast.com/live/113ab1db-1238-f008-367c-c3ab123e557a/95a0fd70-9a99-776e-fb3e-d971e3d346fb

### News and Administrative Orders
- **News Page**: https://www.courts.ri.gov/News/Pages/News.aspx
- **Administrative Orders**: Available via the ood.aspx search page

---

## Opinion URL Patterns

### Supreme Court Opinions
```
https://www.courts.ri.gov/Opinions/Supreme-{YY}-{Number}.pdf
```
Where:
- `{YY}` = Two-digit year (e.g., "25" for 2025, "24" for 2024)
- `{Number}` = Case number within that year

#### Example URLs
```
# Supreme Court Opinion
https://www.courts.ri.gov/Opinions/Supreme-25-21.pdf
https://www.courts.ri.gov/Opinions/Supreme-24-269.pdf
https://www.courts.ri.gov/Opinions/Supreme-24-203.pdf
https://www.courts.ri.gov/Opinions/Supreme-2024-0149.pdf  # Alternative format with 4-digit year
```

### Superior Court Decisions
```
https://www.courts.ri.gov/Decisions/Superior-{CaseType}-{Year}-{Number}.pdf
```
Where:
- `{CaseType}` = Case type abbreviation (e.g., "PC", "PP", "PM")
- `{Year}` = Four-digit year
- `{Number}` = Case number (may be zero-padded)

#### Example URLs
```
# Superior Court Decisions
https://www.courts.ri.gov/Decisions/Superior-PC-2022-04877.pdf
https://www.courts.ri.gov/Decisions/Superior-PP-2024-3180.pdf
https://www.courts.ri.gov/Decisions/Superior-PM-2023-0250.pdf
https://www.courts.ri.gov/Decisions/Superior-PP-2022-3034.pdf
```

### Published Orders
```
https://www.courts.ri.gov/Published Orders/Supreme-{YY}-{Number}.pdf
```

#### Example URLs
```
https://www.courts.ri.gov/Published Orders/Supreme-24-328.pdf
```

### Administrative Orders
```
https://www.courts.ri.gov/Administrative%20Orders/{Court}-{Year}-{Number}.pdf
```
Where:
- `{Court}` = Court abbreviation (e.g., "District", "Superior")

#### Example URLs
```
https://www.courts.ri.gov/Administrative%20Orders/District-2026-02.pdf
https://www.courts.ri.gov/Administrative%20Orders/Superior-2025-15.pdf
```

---

## Case Docket URL Patterns

### Public Portal Case Search
The Rhode Island Judiciary Public Portal provides case search functionality:
```
https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/29
```

### Search Options
The Smart Search supports:
- Record Number or Name search (Last, First Middle Suffix format)
- Filter by Location (All Rhode Island Courts or specific court)
- Filter by Search Type
- Party Name, Nickname, Business Name, Sounds Like searches
- Date of Birth range
- Phone Number, FBI Number, SO Number, State ID, Booking Number
- Case Type, Case Status, File Date range
- Judicial Officer filter
- Warrant searches (Type, Status, Issued Date range)

### Case Number Formats
Based on the decisions and opinions, case numbers follow patterns like:
- **Supreme Court**: `{Year}-{Number}-Appeal.` or `{Year}-{Number}-M.P.` or `{Year}-{Number}-C.A.`
- **Superior Court**: `{CaseType}-{Year}-{Number}` (e.g., PC-2022-4877, PP-2024-3180)

---

## Current Justices - Supreme Court

| Position | Name | Notes |
|----------|------|-------|
| Chief Justice | Hon. Paul A. Suttell | 15+ years as Chief Justice, 40 years on the bench |
| Associate Justice | | |
| Associate Justice | | |
| Associate Justice | | |
| Associate Justice | | |

**Note**: Individual justice biography pages were not found on the courts.ri.gov website. The "About the Supreme Court" PDF at https://www.courts.ri.gov/Courts/SupremeCourt/Documents/AboutTheSupremeCourt.pdf may contain additional details.

---

## Key Contacts

### Supreme Court Administration
- **Meredith A. Benoit, Esquire** - Clerk of the Supreme Court
  - Phone: (401) 222-3272
  - Email: mbenoit@courts.ri.gov

### State Court Administration
- **Julie P. Hamil, Esquire** - State Court Administrator
  - Phone: (401) 222-3263
  - Email: jhamil@courts.ri.gov

- **Gail M. Valuk, Esquire** - Deputy State Court Administrator
  - Phone: (401) 222-3263
  - Email: gvaluk@courts.ri.gov

- **Alexandra E. Kriss** - Assistant Administrator of Community Outreach and Public Relations
  - Phone: (401) 222-4580
  - Email: akriss@courts.ri.gov

### Other Key Contacts
- **Stephen Kerr** - Assistant Administrator of Facilities, Operations, and Security
- **Adejuwon Aikulola** - Assistant Administrator of Judicial Technology Center
- **Darlene Leyden Walsh** - Assistant Administrator of Finance and Budget
- **Mike Sligar, Esquire** - Assistant State Court Administrator of Employee Relations

---

## Opinion Types and Document Categories

### Document Types Available via OOD Search
1. **Opinions** - Full written opinions from the Supreme Court
2. **Decisions** - Written decisions from trial courts (Superior, Family, etc.)
3. **Published Orders** - Significant orders published by the courts
4. **Executive Orders** - Orders from the Chief Justice
5. **Administrative Orders** - Operational orders for court administration
6. **Miscellaneous Orders** - Other court orders

### Courts Covered in OOD Search
- Supreme Court
- Superior Court
- Family Court
- District Court
- Workers' Compensation Court
- Rhode Island Traffic Tribunal
- Ethics Advisory Panel

---

## Access Restrictions

### No Login Required
- Opinion search and viewing on courts.ri.gov
- Opinion/Decision/Order PDF downloads
- Court calendars and oral argument schedules
- Livestream access (via Dacast)
- Public Portal basic case search
- Court rules and legal resources
- News and administrative orders

### Login Required (Attorneys and External Agencies)
- Enhanced Public Portal features
- Electronic filing
- Secure document access

### CAPTCHA Protection
The Public Portal Smart Search uses reCAPTCHA verification for case searches.

---

## Oral Arguments

### Livestreaming
- Remote oral arguments are conducted via audio streaming through Dacast
- Public can listen to hearings in real time at scheduled date/time
- Oral arguments are audio-only

### Scheduling Information
- Monthly Oral Argument Calendar available as PDF
- Hearing Dates for 2025-2026 term available as PDF
- Calendar includes: calendar type, date, time, case number, parties, and attorneys of record

---

## Technical Implementation Notes

### Website Architecture
- **Primary Domain**: www.courts.ri.gov (SharePoint-based site)
- **Portal Domain**: publicportal.courts.ri.gov (Tyler Technologies Odyssey platform)
- SharePoint site uses modern web design with JavaScript-heavy interfaces
- Public Portal version: 2017.1.53.9

### Opinion Search System
The published opinions search at `/Courts/SupremeCourt/Pages/published-opinions.aspx` provides:
- Year filter (checkboxes from 1999 to present)
- Full-text search
- Language preference setting
- Pagination (10 results per page)
- About 3,028 total published opinions

### Unified OOD Search
The `/Pages/ood.aspx` search provides:
- Court filter (checkboxes for all 6 courts + Ethics Panel)
- Type filter (Opinions, Decisions, Orders, etc.)
- Year filter (2013 to present)
- Full-text search
- About 12,078 total results
- Alert subscription option
- Advanced search available

### Data Availability by Date Range
- **Published Opinions**: 1999 to present (based on year filter)
- **OOD Search**: 2013 to present (based on year filter)

### No RSS Feed
No RSS feed was found for opinions or court news. Monitoring would require scraping the search pages.

---

## Courthouse Locations

### Frank J. Licht Judicial Complex (Supreme & Superior Courts)
- 250 Benefit Street, Providence, RI 02903
- ~198,000 square feet
- Built 1928-1933, renamed 1986

### J. Joseph Garrahy Judicial Complex (Superior, Family, District, Workers' Comp)
- 1 Dorrance Plaza, Providence, RI 02903
- ~195,000 square feet
- Dedicated 1980

### Philip W. Noel Judicial Complex (Kent County)
- 222 Quaker Lane, Warwick, RI 02886
- ~195,000 square feet
- Opened 2006

### Florence K. Murray Judicial Complex (Newport County)
- 45 Washington Square, Newport, RI 02840
- ~23,700 square feet
- Original 1927, expanded 1990

### J. Howard McGrath Judicial Complex (Washington County)
- 4800 Tower Hill Road, Wakefield, RI 02879
- ~40,300 square feet
- Dedicated 1988

### Rhode Island Traffic Tribunal
- 670 New London Avenue, Cranston, RI 02920
- ~86,000 square feet
- Opened 2007

### Judicial Records Center
- 5 Hill Street, Pawtucket, RI 02860
- Central repository for semi-active, inactive, and archival court records

---

## Example URLs

```
# Published Opinions Search
GET https://www.courts.ri.gov/Courts/SupremeCourt/Pages/published-opinions.aspx

# OOD Search (All Courts)
GET https://www.courts.ri.gov/Pages/ood.aspx

# Supreme Court Home
GET https://www.courts.ri.gov/Courts/SupremeCourt/Pages/default.aspx

# About the Supreme Court PDF
GET https://www.courts.ri.gov/Courts/SupremeCourt/Documents/AboutTheSupremeCourt.pdf

# Opinion PDF (example)
GET https://www.courts.ri.gov/Opinions/Supreme-25-21.pdf

# Decision PDF (example)
GET https://www.courts.ri.gov/Decisions/Superior-PC-2022-04877.pdf

# Public Portal Case Search
GET https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/29

# Court Calendar
GET https://www.courts.ri.gov/Pages/public-access-supreme.aspx

# Oral Argument Calendar PDF
GET https://www.courts.ri.gov/Courts/SupremeCourt/Documents/Oral_Argument_Calendar.pdf

# Court Rules
GET https://www.courts.ri.gov/Legal-Resources/Pages/court-rules.aspx

# News Page
GET https://www.courts.ri.gov/News/Pages/News.aspx
```

---

## Example Cases

### Recent Supreme Court Cases (January 2026)
- **Clifton Peasley v. City of Providence** - No. 2025-0021-Appeal - Affirmed dismissal under election of remedies doctrine
- **Alicia Andrew v. Richard Adorno** - No. 2024-0269-Appeal - Vacated and remanded regarding standard of evidence
- **1100 North Main LLC v. Shoreby Hill Properties, Inc.** - No. 2024-0203-Appeal - Affirmed judgment, statute of frauds issue
- **Louis Paolino et al. v. Joseph Ferreira et al.** - No. 2024-0149-Appeal - Affirmed amended judgment

### Recent Superior Court Decisions (January 2026)
- **Walter S. Felag, Jr. v. Anthony Patriarca** - No. PC-2022-4877
- **City of Providence v. Sergeant Joseph Hanley** - No. PC-2025-3678
- **Erin Malloy v. David C. Fixler** - No. PP-2024-3180
- **Matthew Marcotte v. State of Rhode Island** - No. PM-2023-0250

---

## Social Media

- **Twitter/X**: @RIJudiciary (https://twitter.com/RIJudiciary)
- **LinkedIn**: Rhode Island Supreme Court (https://www.linkedin.com/company/rhode-island-supreme-court/)

---

## Notes

1. **No Intermediate Appellate Court**: Rhode Island is one of only two states (along with Nebraska) without an intermediate appellate court. All appeals from trial courts go directly to the Supreme Court.

2. **Life Tenure**: Rhode Island Supreme Court justices serve for life during good behavior, making it one of the few states with such tenure.

3. **Unified Court System**: All six courts operate under the administrative supervision of the Chief Justice through the State Court Administrator.

4. **Tyler Technologies Platform**: The Public Portal uses Tyler Technologies' Odyssey system, which is common among state courts.

5. **SharePoint Backend**: The main courts.ri.gov website appears to be built on Microsoft SharePoint.

6. **No Individual Justice Bios**: Unlike many other states, the Rhode Island Judiciary website does not appear to have individual biography pages for the justices.

7. **Historical Coverage**: Published opinions go back to 1999, providing about 25+ years of searchable opinions.

8. **PDF-Based Documents**: Most court documents (opinions, orders, calendars) are provided as PDF downloads rather than HTML pages.

9. **reCAPTCHA Protection**: The Public Portal requires CAPTCHA verification, which may complicate automated scraping.

10. **Audio-Only Streaming**: Oral arguments are streamed as audio only through Dacast, not video.
