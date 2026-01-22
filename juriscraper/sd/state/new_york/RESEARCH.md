# New York Courts Research

## Court Structure

New York has a complex court structure that is often confusing because the naming conventions differ from most other states. The "Supreme Court" is actually the trial court, while the "Court of Appeals" is the highest court.

### 1. New York Court of Appeals
- **Website**: https://www.nycourts.gov/ctapps/
- Highest court in New York State
- 7 Judges (1 Chief Judge + 6 Associate Judges)
- Judges appointed by Governor with Senate confirmation for 14-year terms
- Located at Court of Appeals Hall, Albany, NY

#### Jurisdiction
- Final appellate court for all state courts
- Primarily discretionary review through "leave to appeal"
- Direct appeals in cases where Appellate Division justice dissents on law
- Death penalty cases (automatic review)
- Chief Judge is head of the Unified Court System

### 2. Appellate Division of the Supreme Court (4 Departments)
- **Website**: https://ww2.nycourts.gov/decisions/ad.shtml
- Intermediate appellate court
- Divided into 4 geographic Departments:
  - **1st Department**: Manhattan, Bronx (https://www.nycourts.gov/courts/ad1/)
  - **2nd Department**: Brooklyn, Queens, Staten Island, Nassau, Suffolk, Westchester, Rockland, Putnam, Orange, Dutchess (https://www.nycourts.gov/courts/ad2/)
  - **3rd Department**: Albany area, 28 counties (https://www.nycourts.gov/ad3/)
  - **4th Department**: Rochester/Buffalo area, 22 counties (https://www.nycourts.gov/courts/ad4/)

### 3. Appellate Terms (1st and 2nd Departments only)
- Intermediate appellate court for lower court appeals
- Hears appeals from NYC Civil Court, NYC Criminal Court, District Courts, and lower courts

### 4. Supreme Court (Trial Court)
- **Website**: https://iapps.courts.state.ny.us/webcivil/FCASMain
- General jurisdiction trial court (confusingly named)
- 62 counties, organized into 13 Judicial Districts
- Civil and criminal matters

### 5. Court of Claims
- **Website**: https://ww2.nycourts.gov/COURTS/nyscourtofclaims/
- Claims against the State of New York

### 6. Other Trial Courts
- Family Court (62 courts, one per county)
- Surrogate's Court (62 courts, probate and estate matters)
- County Court (outside NYC, felony cases)
- NYC Civil Court
- NYC Criminal Court
- City Courts (61 city courts outside NYC)
- District Courts (Nassau and Suffolk Counties)
- Town and Village Justice Courts (1,200+ courts)

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://www.nycourts.gov/
- **eCourts System**: https://iapps.courts.state.ny.us/webcivil/ecourtsMain
- **Decisions Hub**: https://ww2.nycourts.gov/decisions/index.shtml

### Court of Appeals
- **Court of Appeals Home**: https://www.nycourts.gov/ctapps/
- **Decisions by Month**: https://www.nycourts.gov/ctapps/decisions.htm
- **Advanced Decision Search**: https://iapps.courts.state.ny.us/lawReporting/CourtOfAppealsSearch
- **Public Access & Search (Court-PASS)**: https://courtpass.nycourts.gov/
- **Oral Arguments Live**: https://www.nycourts.gov/ctapps/live.html
- **Oral Argument Archive**: https://www.nycourts.gov/ctapps/OA-Archives.htm
- **Court Calendar**: https://www.nycourts.gov/ctapps/calendar/2026/COA2026Calendar.pdf
- **Digital Submissions**: https://www.nycourts.gov/ctapps/digitalsubmissions.htm

### Appellate Division Decisions
- **1st Dept. Decisions**: https://www.nycourts.gov/reporter/slipidx/aidxtable_1.shtml
- **2nd Dept. Decisions**: https://www.nycourts.gov/reporter/slipidx/aidxtable_2.shtml
- **3rd Dept. Decisions**: https://decisions.courts.state.ny.us/ad3/
- **4th Dept. Decisions**: https://www.nycourts.gov/courts/ad4/clerk/decisions/

### Law Reporting Bureau (All Courts Search)
- **Main Search**: https://iapps.courts.state.ny.us/lawReporting/Search
- Courts available: Court of Appeals, All 4 Appellate Divisions, Appellate Terms, Commercial Division, Other Courts
- Data from 1983 to present

### Trial Courts Search
- **Case Papers & Decisions Search**: https://iapps.courts.state.ny.us/search/begin
- **WebCivil Supreme**: https://iapps.courts.state.ny.us/webcivil/FCASMain
- **WebCivil Local**: https://iapps.courts.state.ny.us/webcivilLocal/LCMain
- **WebCriminal**: https://iapps.courts.state.ny.us/webcrim_attorney/AttorneyWelcome
- **WebFamily**: https://iapps.courts.state.ny.us/fcasfamily/main

### Electronic Filing (NYSCEF)
- **Home**: https://iapps.courts.state.ny.us/nyscef/HomePage
- **Guest Search**: https://iapps.courts.state.ny.us/nyscef/CaseSearch
- Supports: Appellate Court, Supreme Court, Civil Court, Family Court, Surrogate Court, Court of Claims, Superior Criminal Court

### Official Reports
- **Official Reports (NY Reports, AD Reports)**: https://www.nycourts.gov/reporter/Decisions.shtml

---

## Court of Appeals Decision URL Patterns

### Decision Lists by Month
- **Pattern**: `https://www.nycourts.gov/ctapps/Decisions/{YYYY}/{Mon}{YY}/{Month}{YY}.html`
- **Example**: `https://www.nycourts.gov/ctapps/Decisions/2026/Jan26/January26.html`
- **Example**: `https://www.nycourts.gov/ctapps/Decisions/2025/Dec25/December25.html`

### Individual Decision PDFs
- **Pattern**: `https://www.nycourts.gov/ctapps/Decisions/{YYYY}/{Mon}{YY}/{filename}.pdf`
- Filenames typically match case numbers or slip opinion numbers

### Slip Opinion Numbers
- **Format**: `YYYY NY Slip Op NNNNN`
- **Example**: `2026 NY Slip Op 00201`

### Official Reports Citations
- **Court of Appeals**: `NY3d` (e.g., 3 NY3d 244)
- **Appellate Division**: `AD3d` (e.g., 125 AD3d 1272)
- **Miscellaneous**: `Misc 3d`

---

## Appellate Division URL Patterns

### 1st Department
- **Decisions by Year**: `/reporter/slipidx/aidxtable_1.shtml`
- Data available from 2003 to present

### 2nd Department
- **Decisions by Year**: `/reporter/slipidx/aidxtable_2.shtml`

### 3rd Department
- **Decision Calendars**: `https://decisions.courts.state.ny.us/ad3/`
- Organized by date within each month

### 4th Department
- **Decisions by Year**: `https://www.nycourts.gov/courts/ad4/clerk/decisions/{YYYY}/`
- **Motions**: `https://www.courts.state.ny.us/reporter/motindex/mots_ad4_list.shtml`
- **Attorney Disciplinary**: `https://www.nycourts.gov/courts/ad4/clerk/decisions/{YYYY}/disciplinary.shtm`
- **Voluntary Resignations**: `https://www.nycourts.gov/courts/ad4/clerk/decisions/{YYYY}/voluntary.shtm`

---

## Current Judges - Court of Appeals

| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Hon. Rowan D. Wilson | Chief Judge | Feb 6, 2017 (Associate); Apr 18, 2023 (Chief) | https://www.nycourts.gov/ctapps/jwilson.htm |
| Hon. Jenny Rivera | Associate Judge | Feb 11, 2013 | https://www.nycourts.gov/ctapps/jrivera.htm |
| Hon. Michael J. Garcia | Associate Judge | Feb 6, 2016 | https://www.nycourts.gov/ctapps/jgarcia.htm |
| Hon. Madeline Singas | Associate Judge | Mar 23, 2021 | https://www.nycourts.gov/ctapps/jsingas.htm |
| Hon. Anthony Cannataro | Associate Judge | Apr 18, 2023 | https://www.nycourts.gov/ctapps/jcannataro.htm |
| Hon. Shirley Troutman | Associate Judge | Apr 18, 2023 | https://www.nycourts.gov/ctapps/jtroutman.htm |
| Hon. Caitlin J. Halligan | Associate Judge | Sept 12, 2023 | https://www.nycourts.gov/ctapps/jhalligan.htm |

**Notes**:
- Chief Judge Wilson was previously a partner at Cravath, Swaine & Moore
- Judges serve 14-year terms
- Chief Judge Wilson became Chief Judge in April 2023 after being an Associate Judge since 2017

---

## Current Justices - Appellate Division, 1st Department

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Dianne T. Renwick | Presiding Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Renwick.shtml |
| Hon. Sallie Manzanet-Daniels | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Manzanet-Daniels.shtml |
| Hon. Troy K. Webber | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Webber.shtml |
| Hon. Cynthia S. Kern | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Kern.shtml |
| Hon. Peter H. Moulton | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Moulton.shtml |
| Hon. Tanya R. Kennedy | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Kennedy.shtml |
| Hon. Saliann Scarpulla | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Scarpulla.shtml |
| Hon. David Friedman | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Friedman.shtml |
| Hon. Barbara R. Kapnick | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Kapnick.shtml |
| Hon. Ellen Gesmer | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Gesmer.shtml |
| Hon. Lizbeth González | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Gonzalez.shtml |
| Hon. Manuel J. Mendez | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Mendez.shtml |
| Hon. Martin Shulman | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Shulman.shtml |
| Hon. Julio Rodriguez III | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Rodriguez.shtml |
| Hon. Bahaati Pitt-Burke | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Pitt.shtml |
| Hon. John R. Higgitt | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Higgitt.shtml |
| Hon. Llinét M. Rosado | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Rosado.shtml |
| Hon. Kelly O'Neill Levy | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_ONeill_Levy.shtml |
| Hon. Marsha Michael | Associate Justice | https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Michael.shtml |
| Hon. Margaret A. Chan | Associate Justice | (Bio coming soon) |
| Hon. Shlomo S. Hagler | Associate Justice | (Bio coming soon) |

---

## Current Justices - Appellate Division, 4th Department

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Gerald J. Whalen | Presiding Justice | https://ad4.nycourts.gov/publications/directory/333 |
| Hon. Stephen K. Lindley | Associate Justice | https://ad4.nycourts.gov/publications/directory/326 |
| Hon. John M. Curran | Associate Justice | https://ad4.nycourts.gov/publications/directory/447 |
| Hon. Tracey A. Bannister | Associate Justice | https://ad4.nycourts.gov/publications/directory/575 |
| Hon. Mark A. Montour | Associate Justice | https://ad4.nycourts.gov/publications/directory/635 |
| Hon. Nancy E. Smith | Associate Justice | https://ad4.nycourts.gov/publications/directory/331 |
| Hon. E. Jeannette Ogden | Associate Justice | https://ad4.nycourts.gov/publications/directory/639 |
| Hon. Donald A. Greenwood | Associate Justice | https://ad4.nycourts.gov/publications/directory/645 |
| Hon. Henry J. Nowak | Associate Justice | https://ad4.nycourts.gov/publications/directory/669 |
| Hon. Scott J. DelConte | Associate Justice | https://ad4.nycourts.gov/publications/directory/672 |
| Hon. Craig D. Hannah | Associate Justice | https://ad4.nycourts.gov/publications/directory/689 |

**Note**: Justices of 2nd and 3rd Departments available at:
- 2nd Dept: https://www.nycourts.gov/courts/ad2/justices.shtml
- 3rd Dept: https://www.nycourts.gov/ad3/about/justices-of-the-court.shtml

---

## Case Number Formats

### Court of Appeals
- **Appeals**: `APL YYYY-NNNNN` (e.g., APL 2025-00077)
- **Motions**: `MO YYYY-NNNNN`

### Appellate Division
- Varies by department, generally follows pattern like:
  - `YYYY-NNNNN` or `CA XX-NNNNN`

### Supreme Court (Trial Level)
- **Index Number Pattern**: `NNN/YYYY` or `NNNNNN/YYYY`
- County-specific numbering

### Slip Opinion Numbers
- **Format**: `YYYY NY Slip Op NNNNN`
- Used statewide for all published appellate opinions

---

## Opinion Types and Publication

### Opinion Categories
1. **Court of Appeals Opinions**: Final decisions (published in NY3d)
2. **Court of Appeals Motions**: Motion decisions
3. **Appellate Division Opinions**: Published in AD3d
4. **Appellate Division Motions**: Motion decisions by department
5. **Trial Court Opinions**: Select opinions from Supreme Court

### Publication Schedule
- **Court of Appeals**: Decisions released on decision day, posted same day
- **Appellate Division**: Generally released two weeks after argument term concludes
- **4th Dept**: Posted at 3:00 PM on decision dates

### Document Formats
- **All opinions**: PDF format
- **Oral arguments**: Video webcast (live and archived)

---

## Access Restrictions

### No Login Required
- Court of Appeals decisions and search
- Appellate Division decisions
- Law Reporting Bureau search
- Judges' bio pages
- Oral argument archives

### Login Required / hCaptcha Protected
- **eCourts/WebCivil**: Case search (hCaptcha verification)
- **NYSCEF**: Guest search available, registration for filing
- **Court-PASS**: Free registration for enhanced access

### Rate Limiting
- hCaptcha on case search portals
- Standard best practices recommended for scraping

---

## Oral Arguments

### Court of Appeals
- **Live Webcast**: https://www.nycourts.gov/ctapps/live.html
- **Archive**: https://www.nycourts.gov/ctapps/OA-Archives.htm (includes transcripts and closed captioned video)
- **Sessions**: Held in Albany (occasionally travels, e.g., March 2026 in the Bronx)
- **Calendar**: Published annually with session dates
- **Twitter**: @NYCourtsCOA for announcements

### Appellate Divisions
- **4th Dept**: Hybrid oral argument pilot program available
- Arguments generally held at department courthouses

---

## Technical Implementation Notes

### Website Structure
- **Multiple Domains**:
  - www.nycourts.gov (main portal, Court of Appeals)
  - ww2.nycourts.gov (decisions hub, some older content)
  - iapps.courts.state.ny.us (eCourts, search applications)
  - decisions.courts.state.ny.us (3rd Dept decisions)
  - ad4.nycourts.gov (4th Dept API/content)
  - courtpass.nycourts.gov (Court of Appeals public access)

### Search Systems
1. **Law Reporting Bureau Search**: Most comprehensive, covers all courts, 1983-present
2. **Court of Appeals Search**: Court-specific with advanced filters
3. **eCourts/WebCivil**: Trial court case information (hCaptcha protected)
4. **NYSCEF**: E-filing system with guest case search

### Scraping Approach
1. **Court of Appeals Decisions**: Parse monthly decision pages for PDF links
   - URL: `/ctapps/Decisions/{YYYY}/{Mon}{YY}/`
2. **Appellate Division**: Department-specific pages
   - 1st/2nd: Reporter slip index tables
   - 3rd: Decision calendars
   - 4th: Year-based directories
3. **Advanced Search**: Law Reporting Bureau for historical data
4. **Oral Arguments**: Archive page with video links

### Data Availability
- **Court of Appeals**: 1983 to present (via Law Reporting Bureau)
- **Appellate Division 1st Dept**: 2003 to present
- **Appellate Division 4th Dept**: 2013 to present
- **Other courts**: Varies

---

## Example URLs

```
# Court of Appeals decisions by month
GET https://www.nycourts.gov/ctapps/Decisions/2026/Jan26/January26.html

# Court of Appeals advanced search
GET https://iapps.courts.state.ny.us/lawReporting/CourtOfAppealsSearch

# Law Reporting Bureau search (all courts)
GET https://iapps.courts.state.ny.us/lawReporting/Search

# Appellate Division 1st Dept decisions
GET https://www.nycourts.gov/reporter/slipidx/aidxtable_1.shtml

# Appellate Division 4th Dept 2025 decisions
GET https://www.nycourts.gov/courts/ad4/clerk/decisions/2025/

# Court of Appeals oral argument archive
GET https://www.nycourts.gov/ctapps/OA-Archives.htm

# Court of Appeals public access system
GET https://courtpass.nycourts.gov/

# NYSCEF guest case search
GET https://iapps.courts.state.ny.us/nyscef/CaseSearch

# WebCivil Supreme Court search
GET https://iapps.courts.state.ny.us/webcivil/FCASMain

# Judge bio page (Court of Appeals)
GET https://www.nycourts.gov/ctapps/jwilson.htm

# Justice bio page (AD 1st Dept)
GET https://www.nycourts.gov/courts/ad1/justicesofthecourt/Justice_Renwick.shtml

# Justice bio page (AD 4th Dept)
GET https://ad4.nycourts.gov/publications/directory/333
```

---

## Example Cases

### Recent Court of Appeals Cases (2026)
- **People v Gaffney (Luke J.)** - APL 2025-00077 (Feb 2026 session)
- **People v Curry (Eugene)** - APL 2025-00076 (Feb 2026 session)
- **People v Billups (Ricky)** - APL 2025-00108 (Feb 2026 session)
- **Matter of Bi-Coastal Properties v Soliman** - APL 2025-00136 (Mar 2026 session)

### 4th Department Decision Release Schedule (2026)
- February 11
- March 20, 27
- April 24
- May 1
- June 5, 26
- July 24
- October 2, 9
- November 13, 20
- December 23

---

## Contact Information

### Court of Appeals Clerk's Office
- **Phone**: See https://www.nycourts.gov/ctapps/phone.htm
- **Address**: Court of Appeals Hall, 20 Eagle Street, Albany, NY 12207
- **Digital Submissions**: https://www.nycourts.gov/ctapps/digitalsubmissions.htm

### Appellate Division, 1st Department
- **Phone**: (212) 340-0400
- **Address**: 27 Madison Avenue, New York, NY 10010
- **Clerk of Court**: Susanna Molina Rojas

### Appellate Division, 4th Department
- **Phone**: (585) 530-3100
- **Address**: 50 East Avenue, Suite 200, Rochester, NY 14604
- **Clerk of Court**: Ann Dillon Flynn, Esq.
- **Decisions Department**: (585) 530-3132 / (585) 530-3128

### NYSCEF Support
- **Email**: nyscef@nycourts.gov
- **Phone**: (646) 386-3033
- **Fax**: (212) 401-9146

### Social Media
- **Twitter**: @NYCourtsCOA (Court of Appeals)
- **Twitter**: @NYAppDiv4 (4th Department)

---

## Notes

1. **Naming Confusion**: New York's "Supreme Court" is the trial court (general jurisdiction), while the "Court of Appeals" is the highest court. This is opposite of federal court naming and most other states.

2. **Unified Court System**: The NY Unified Court System was established in 1962 and reorganized in 1978. The Chief Judge of the Court of Appeals serves as the administrative head.

3. **Four Appellate Departments**: Each department has its own Presiding Justice, justices, and practices. Decision URL patterns vary by department.

4. **Slip Opinions**: All appellate opinions are assigned statewide slip opinion numbers (YYYY NY Slip Op NNNNN) regardless of which court issues them.

5. **hCaptcha Protection**: Trial court case searches (eCourts) use hCaptcha verification, which may complicate automated scraping.

6. **Court-PASS**: The Court of Appeals' Public Access and Search System provides detailed docket information for cases pending or filed after January 1, 2013.

7. **E-Filing (NYSCEF)**: Mandatory in many courts for attorney filings. Guest access available for case searches without login.

8. **Oral Arguments**: Court of Appeals arguments are webcast live and archived with transcripts and closed captioning.

9. **Decision Release Schedule**:
   - Court of Appeals: Decisions released on decision day
   - 4th Dept: Generally two weeks after term concludes, posted at 3:00 PM
   - Other departments: Varies

10. **Historical Data**: Law Reporting Bureau search provides access to decisions from 1983 to present.
