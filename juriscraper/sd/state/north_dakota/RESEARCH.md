# North Dakota Courts Research

## Court Structure

North Dakota has a unified court system with one appellate court (no intermediate Court of Appeals).

### 1. Supreme Court of North Dakota
- **Website**: https://www.ndcourts.gov/supreme-court
- Highest and only appellate court in North Dakota
- 5 Justices (1 Chief Justice + 4 Associate Justices)
- Justices are elected to 10-year terms in nonpartisan elections
- Located at 600 E Boulevard Ave, Bismarck, ND 58505-0530
- Chief Justice elected by vote of district court judges and Supreme Court justices

#### Jurisdiction
- Final appellate court for all state courts
- Appeals from District Courts
- Appeals from administrative agency decisions
- Original jurisdiction for certain writs (certiorari, habeas corpus, mandamus, prohibition, supervision, injunction)
- Certified questions of law
- Attorney and judge discipline matters

### 2. District Courts (Trial Level)
- **Website**: https://www.ndcourts.gov/district-court
- 8 judicial districts organized into 4 administrative units
- 55 district judges statewide
- General jurisdiction trial courts
- Serve as juvenile courts
- Appellate courts of first instance for administrative agency decisions

#### Judicial Districts
1. East Central District (11 judges, 2 chamber cities)
2. Southwest District (4 judges, 1 chamber city)
3. Southeast District (7 judges, 5 chamber cities)
4. South Central District (10 judges, 4 chamber cities)
5. Northeast District (6 judges, 5 chamber cities)
6. Northeast Central District (6 judges, 1 chamber city)
7. Northwest District (6 judges, 2 chamber cities)
8. North Central District (5 judges, 1 chamber city)

### 3. Municipal Courts
- **Website**: https://www.ndcourts.gov/other-courts/municipal-courts
- Handle city ordinance violations

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://www.ndcourts.gov/
- **Supreme Court Home**: https://www.ndcourts.gov/supreme-court
- **District Courts Home**: https://www.ndcourts.gov/district-court

### Supreme Court
- **Current Justices**: https://www.ndcourts.gov/supreme-court/justices
- **Opinions Search**: https://www.ndcourts.gov/supreme-court/opinions
- **Docket Search**: https://www.ndcourts.gov/supreme-court/docket-search
- **Calendar**: https://www.ndcourts.gov/supreme-court/calendar
- **Filing Information**: https://www.ndcourts.gov/supreme-court/filing
- **Watch/Listen to Court**: https://www.ndcourts.gov/supreme-court/listen-to-court
- **History**: https://www.ndcourts.gov/supreme-court/history-of-the-supreme-court
- **Surrogate Judges**: https://www.ndcourts.gov/supreme-court/surrogate-judges

### New Appellate Case System (April 2024)
- **Public Portal Home**: https://portal.ctrack.ndcourts.gov/portal/home
- **Search**: https://portal.ctrack.ndcourts.gov/portal/search
- **Case Search**: https://portal.ctrack.ndcourts.gov/portal/search/case
- **Party Search**: https://portal.ctrack.ndcourts.gov/portal/search/party
- **Calendar Search**: https://portal.ctrack.ndcourts.gov/portal/search/calendar
- **Document Search**: https://portal.ctrack.ndcourts.gov/portal/search/document
- **Publication Search**: https://portal.ctrack.ndcourts.gov/portal/search/publication

---

## Opinion URL Patterns

### Opinion Search Page (Primary)
- **Base URL**: `https://www.ndcourts.gov/supreme-court/opinions`
- **With pagination**: `https://www.ndcourts.gov/supreme-court/opinions?page={N}` (0-indexed)
- Supports filtering by: Topic, Author, Citation, Trial Judge, Search Query
- 12,137+ total opinions available
- Results ordered by newest by default

### Individual Opinion URLs
- **Pattern**: Internal database IDs, not directly navigable by citation
- Opinions are accessed via the search interface
- Each opinion has a "View Opinion" button that opens a PDF or detail view

### Citation Format
- **Format**: `YYYY ND NNN` (e.g., `2026 ND 7`)
- **Northwestern Reporter**: Parallel citations in N.W.2d or N.W.3d

### Appellate Case System URLs
- **Case Detail Pattern**: `https://portal.ctrack.ndcourts.gov/portal/court/{courtID}/case/{caseID}`
- **Court ID (Supreme Court)**: `68f021c4-6a44-4735-9a76-5360b2e8af13`
- **Example**: `https://portal.ctrack.ndcourts.gov/portal/court/68f021c4-6a44-4735-9a76-5360b2e8af13/case/167bc5ac-dcde-4911-a026-e83fc2888978`

---

## Current Justices - Supreme Court

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Lisa K. Fair McEvers | Chief Justice | https://www.ndcourts.gov/supreme-court/justices/lisakfairmcevers |
| Hon. Daniel J. Crothers | Justice | https://www.ndcourts.gov/supreme-court/justices/danieljcrothers |
| Hon. Jerod E. Tufte | Justice | https://www.ndcourts.gov/supreme-court/justices/jerodetufte |
| Hon. Jon J. Jensen | Justice | https://www.ndcourts.gov/supreme-court/justices/jonjjensen |
| Hon. Douglas A. Bahr | Justice | https://www.ndcourts.gov/supreme-court/justices/DouglasABahr |

**Notes**:
- Chief Justice Lisa K. Fair McEvers: Appointed to Supreme Court in 2014, elected Chief Justice in December 2025
- Justices serve 10-year terms
- Chief Justice elected by vote of district court judges and Supreme Court justices
- Note: News from January 2026 indicates a vacancy - Judicial Nominating Committee forwarded six names to Governor for appointment

---

## Case Number Formats

### Supreme Court Cases
- **Format**: `YYYYNNNN` (8-digit year + sequential number)
- **Example**: `20260033`, `20250208`
- YY/YYYY = Year case was filed
- NNNN = Sequential number within year

### Originating Court Cases
- **Format**: `{DistrictCode}-{Year}-{Type}-{Number}`
- **Example**: `08-2025-CV-03307` (Burleigh County District Court)

---

## Opinion Types and Publication

### Case Classifications
- Appeal - Administrative (DOT, Industrial Commission, Unemployment, Workers Comp, Zoning, Other)
- Appeal - Civil (Adoption, Child Support, Constitutional Law, Contracts, Corporations, Divorce, etc.)
- Appeal - Criminal (Arson, Assault, DUI, Drugs, Homicide, Sexual Offense, Theft, etc.)
- Appeal - Juvenile (Delinquency, Deprivation, Termination of Parental Rights)
- Board of Law Examiners
- Certified Question (Civil, Criminal)
- Discipline - Attorney (Disbarment, Suspension, Disability, Reciprocal)
- Discipline - Judge
- Judicial Administration (Rule, Vacancy)
- Original Proceeding (Writs - Certiorari, Habeas Corpus, Injunction, Mandamus, Prohibition, Supervision)

### Citation System
- **North Dakota Reports**: YYYY ND NNN (e.g., 2026 ND 7)
- **Northwestern Reporter**: Parallel citations in N.W.2d or N.W.3d

---

## Access Restrictions

### No Login Required
- All Supreme Court opinions
- Opinion search and filtering
- Docket search (new portal)
- Case search
- Party search
- Calendar search
- Document search
- Publication search
- Justice biographies
- Oral argument recordings (since Jan. 1, 2001)

### Login Required
- E-filing (attorneys required to e-file)
- Registration for e-filing service

### Rate Limiting
- No apparent CAPTCHA or aggressive rate limiting observed
- Standard best practices recommended for scraping

---

## Oral Arguments

### Live Streaming
- **YouTube Channel**: https://www.youtube.com/channel/UCdGGOLvrwBQq1TzPrnJfHOQ
- All oral arguments are webcast live (except when Court is "on the road")
- Audio streaming available on website

### Recordings
- Available since January 1, 2001
- Recordings posted within 24 hours of argument (when in Bismarck)
- Accessible via "Oral Argument Recording" docket entry in each case
- Search for cases at: https://portal.ctrack.ndcourts.gov/portal/search

### Calendar
- Available via public portal calendar search
- Quick links for next 7 days and next 30 days

---

## Technical Implementation Notes

### Website Architecture
- **Primary Domain**: www.ndcourts.gov
- **New Appellate Portal**: portal.ctrack.ndcourts.gov (Thomson Reuters Case Management Systems)
- Portal went live April 8, 2024
- Operates on Central Standard Time for filing deadlines

### Search Systems
1. **Opinion Search** (www.ndcourts.gov/supreme-court/opinions): Best for searching published opinions with filters
2. **Appellate Case System** (portal.ctrack.ndcourts.gov): For dockets, documents, parties, calendars
3. **Publication Search**: For notices and opinions via portal

### Scraping Approach
1. **Recent Opinions**: Use the opinion search page with pagination
   - URL: `https://www.ndcourts.gov/supreme-court/opinions`
   - Default sort: Newest first
   - 10, 50, or 100 results per page
2. **Historical Data**: Use pagination through opinion search
3. **Dockets/Documents**: Use new appellate portal case search
4. **Bulk Processing**: Results limited to 10,000 records in portal searches

### Data Availability
- **Opinions**: 12,137+ opinions available
- **Oral Arguments**: Recordings since January 1, 2001
- **New Portal**: April 8, 2024 to present (not all historical data searchable)

---

## Example URLs

```
# Opinion search main page
GET https://www.ndcourts.gov/supreme-court/opinions

# Opinion search with pagination
GET https://www.ndcourts.gov/supreme-court/opinions?page=2

# Current justices page
GET https://www.ndcourts.gov/supreme-court/justices

# Individual justice bio
GET https://www.ndcourts.gov/supreme-court/justices/lisakfairmcevers

# Appellate portal home
GET https://portal.ctrack.ndcourts.gov/portal/home

# Case search
GET https://portal.ctrack.ndcourts.gov/portal/search/case

# Case search results (all cases, newest first)
GET https://portal.ctrack.ndcourts.gov/portal/search/case/results?criteria=~(advanced~false~courtID~%2768f021c4-6a44-4735-9a76-5360b2e8af13~paging~(totalItems~0~itemsPerPage~25~page~1~sortBy~%27caseHeader.filedDate~sortDesc~true)~case~(caseNumberQueryTypeID~10463~caseTitleQueryTypeID~300054~originatingCourtCaseNumberQueryTypeID~10463~excludeClosed~false))

# Individual case detail
GET https://portal.ctrack.ndcourts.gov/portal/court/68f021c4-6a44-4735-9a76-5360b2e8af13/case/167bc5ac-dcde-4911-a026-e83fc2888978

# Calendar page
GET https://www.ndcourts.gov/supreme-court/calendar

# Watch/Listen to court
GET https://www.ndcourts.gov/supreme-court/listen-to-court

# YouTube oral arguments
GET https://www.youtube.com/channel/UCdGGOLvrwBQq1TzPrnJfHOQ
```

---

## Example Cases

### Recent Supreme Court Cases (January 2026)
- **State v. Krall** - 2026 ND 7 (Docket 20240233) - Appeal - Criminal - Homicide
- **Ziemann v. Grosz** - 2026 ND 6 (Docket 20250164) - Appeal - Civil - Other
- **Gum v. Muddy Boyz Drywall** - 2026 ND 5 (Docket 20250324) - Appeal - Civil - Contracts
- **Weigel, et al. v. Albertson** - 2026 ND 4 (Docket 20250342) - Appeal - Civil - Other
- **Rangel v. State** - 2026 ND 3 (Docket 20250281) - Appeal - Civil - Post-Conviction Relief
- **State v. Mogren** - 2026 ND 2 (Docket 20250266) - Appeal - Criminal - Other
- **Pederson v. State** - 2026 ND 1 (Docket 20250208) - Appeal - Civil - Post-Conviction Relief

---

## Contact Information

### Supreme Court Clerk's Office
- **Phone**: (701) 328-2221
- **Email**: supclerkofcourt@ndcourts.gov
- **Hours**: 8:00 AM - 5:00 PM (Central Time)
- **Physical Address**: 600 E Boulevard Ave, Bismarck, ND 58505-0530

### Technical Support
- **Email**: helpdesk@ndcourts.gov
- **Phone**: (701) 328-4218

### Social Media
- **YouTube**: https://www.youtube.com/channel/UCdGGOLvrwBQq1TzPrnJfHOQ

---

## Notes

1. **No Intermediate Appellate Court**: North Dakota is one of the few states with no Court of Appeals; all appeals go directly to the Supreme Court.

2. **New Case Management System**: The appellate portal (portal.ctrack.ndcourts.gov) launched April 8, 2024. Historical data may not be fully searchable through this system.

3. **E-Filing Requirement**: Attorneys are required to e-file. Self-represented parties may also e-file but are not required to.

4. **Time Zone**: The system operates on Central Standard Time. Filing deadlines are based on CST.

5. **Justice Biographies**: URL pattern uses lowercased name without spaces (e.g., `/supreme-court/justices/lisakfairmcevers`), except some use mixed case (e.g., `/DouglasABahr`).

6. **10,000 Record Limit**: Portal search results are limited to 10,000 records. Refine searches for complete results.

7. **Payment Processing**: Filing fees processed through "nCourt*ND Supreme Court" - users warned not to dispute these charges.

8. **Thomson Reuters System**: The appellate case system is powered by Thomson Reuters Case Management Systems.

9. **Oral Argument Archive**: Recordings available since 2001, typically posted within 24 hours of argument.

10. **Current Vacancy**: As of January 2026, there is a vacancy on the Supreme Court with nominations forwarded to the Governor.
