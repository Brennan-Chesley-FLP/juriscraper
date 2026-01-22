# Ohio Courts Research

## Court Structure

Ohio has a comprehensive court system with a Supreme Court and 12 intermediate appellate courts (Courts of Appeals).

### 1. Supreme Court of Ohio
- **Website**: https://www.supremecourt.ohio.gov/
- Highest court in Ohio
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- Justices are elected to 6-year terms; two justices elected in even-numbered years
- Justices must be attorneys with at least 6 years of experience in the practice of law
- Located at 65 S. Front Street, Columbus, OH 43215-3431
- Phone: 614.387.9000

#### Jurisdiction
- Final appellate court for all state courts
- Original jurisdiction for writs of habeas corpus, mandamus, procedendo, prohibition, and quo warranto
- Appeals from Courts of Appeals, Board of Tax Appeals, Public Utilities Commission
- Death penalty appeals
- Attorney and judge discipline matters
- Certified conflict cases between appellate districts
- Certified questions of state law

### 2. Courts of Appeals (12 Districts)
- **Overview Page**: https://www.supremecourt.ohio.gov/courts/judicial-system/ohio-court-of-appeals/
- Intermediate appellate courts
- Each district covers specific counties
- Cases heard by 3-judge panels
- Judges elected to 6-year terms
- Number of judges per district varies from 4 to 12

#### District Courts
| District | Counties | Location | Judges |
|----------|----------|----------|--------|
| First | Hamilton | Cincinnati | 6 |
| Second | Multiple | Dayton | Multiple |
| Third | Multiple | Lima | Multiple |
| Fourth | Multiple | Portsmouth | Multiple |
| Fifth | Multiple | Canton | Multiple |
| Sixth | Multiple | Toledo | Multiple |
| Seventh | Multiple | Youngstown | Multiple |
| Eighth | Cuyahoga | Cleveland | 12 |
| Ninth | Multiple | Akron | Multiple |
| Tenth | Franklin | Columbus | Multiple |
| Eleventh | Multiple | Warren | Multiple |
| Twelfth | Multiple | Middletown | Multiple |

### 3. Trial Courts
- **Courts by County**: https://www.supremecourt.ohio.gov/courts/judicial-system/ohio-trial-courts/
- Courts of Common Pleas (General, Domestic Relations, Juvenile, Probate divisions)
- Municipal Courts
- County Courts
- Court of Claims (https://ohiocourtofclaims.gov/)

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://www.supremecourt.ohio.gov/
- **Supreme Court Home**: https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/
- **Courts of Appeals**: https://www.supremecourt.ohio.gov/courts/judicial-system/ohio-court-of-appeals/

### Opinion Search System
- **Opinion Search**: https://www.supremecourt.ohio.gov/Rod/docs/Default.aspx
- **Daily Archive**: https://www.supremecourt.ohio.gov/opinions-cases/daily-archive/

### Docket/Case Search System
- **Public Docket Search**: https://www.supremecourt.ohio.gov/Clerk/ecms/#/search
- **Recent Filings**: https://www.supremecourt.ohio.gov/Clerk/ecms/#/recentfilings
- **Issues Accepted for Review**: https://www.supremecourt.ohio.gov/Clerk/ecms/#/issues
- **User Guide**: https://www.supremecourt.ohio.gov/Clerk/ecms/content/UserGuide.pdf

### Justices
- **Justices Overview**: https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/
- **Historical Justices**: https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-1803-to-present/

### Oral Arguments
- **Oral Argument Calendar**: https://www.supremecourt.ohio.gov/opinions-cases/oral-arguments/oral-argument-calendar/
- **Video Archive (Ohio Channel)**: https://ohiochannel.org/series/supreme-court-of-ohio

---

## Opinion URL Patterns

### Opinion Search Page
- **Base URL**: `https://www.supremecourt.ohio.gov/Rod/docs/Default.aspx`
- **With Source Filter**: `https://www.supremecourt.ohio.gov/Rod/docs/?source={N}`
  - `source=0` or blank = Supreme Court of Ohio
  - `source=1` = First District Court of Appeals
  - `source=2` through `source=12` = District Courts of Appeals
  - `source=13` = Court of Claims
  - `source=14` = Miscellaneous
  - `source=15` = All Sources
  - `source=16` = All District Courts

### Search Parameters
- **Year Decided**: Year range filter (1992-present)
- **County**: Filter by Ohio county (88 counties)
- **Case Number**: Case number search
- **Author**: Opinion author search
- **Topics and Issues**: Subject matter search
- **WebCite No**: Direct citation lookup (e.g., "2026-Ohio-148")
- **Citation**: Traditional citation lookup
- **Opinion Text Search**: Full-text search

### Individual Opinion PDF URLs
- **Pattern**: `https://www.supremecourt.ohio.gov/rod/docs/pdf/{district}/{year}/{year}-Ohio-{number}.pdf`
- **Supreme Court (district 0)**: `https://www.supremecourt.ohio.gov/rod/docs/pdf/0/2026/2026-Ohio-148.pdf`
- **First District**: `https://www.supremecourt.ohio.gov/rod/docs/pdf/1/2026/2026-Ohio-XXX.pdf`
- District numbers 0-12 correspond to Supreme Court and Courts of Appeals

### Citation Format
- **WebCite Format**: `YYYY-Ohio-NNN` (e.g., `2026-Ohio-148`)
- **Slip Opinion Format**: `Slip Opinion No. YYYY-Ohio-NNN`
- **Official Ohio Reports**: Parallel citations available

---

## Case Docket URL Patterns

### Case Information Page
- **Pattern**: `https://www.supremecourt.ohio.gov/Clerk/ecms/#/caseinfo/{year}/{number}`
- **Example**: `https://www.supremecourt.ohio.gov/Clerk/ecms/#/caseinfo/2024/0749`

### Case Number Format
- **Format**: `YYYY-NNNN` (e.g., `2024-0749`)
- Year = Year case was filed
- NNNN = Sequential number (zero-padded to 4 digits)

### Docket Document PDFs
- **Pattern**: `https://www.supremecourt.ohio.gov/pdf_viewer/pdf_viewer.aspx?pdf={pdfId}.pdf&subdirectory={caseNumber}\DocketItems&source=DL_Clerk`
- **Example**: `https://www.supremecourt.ohio.gov/pdf_viewer/pdf_viewer.aspx?pdf=963255.pdf&subdirectory=2024-0749\DocketItems&source=DL_Clerk`

### Decision Document PDFs
- **Pattern**: `https://www.supremecourt.ohio.gov/pdf_viewer/pdf_viewer.aspx?pdf={pdfId}.pdf&subdirectory={caseNumber}\DecisionItems&source=DL_Clerk`

---

## Current Justices - Supreme Court

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Sharon L. Kennedy | Chief Justice | https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/sharon-kennedy/ |
| Hon. Patrick F. Fischer | Justice | https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/patrick-fischer/ |
| Hon. R. Patrick DeWine | Justice | https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/patrick-dewine/ |
| Hon. Jennifer Brunner | Justice | https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/jennifer-brunner/ |
| Hon. Joseph T. Deters | Justice | https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/joseph-deters/ |
| Hon. Daniel R. Hawkins | Justice | https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/daniel-hawkins/ |
| Hon. Megan E. Shanahan | Justice | https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/megan-shanahan/ |

**Notes**:
- Chief Justice Sharon L. Kennedy leads the Court
- Justices serve 6-year terms
- Two justices elected in even-numbered years (three in years when Chief Justice is up)

---

## Case Types

The Ohio Supreme Court handles many case types including:
- **Appeals**: Discretionary appeals (felony/non-felony), Appeals of Right, Direct Appeals
- **Death Penalty Cases**: Direct appeals, postconviction cases
- **Original Actions**: Mandamus, Prohibition, Procedendo, Quo Warranto, Habeas Corpus
- **Disciplinary Cases**: Attorney misconduct, Judge misconduct
- **Administrative Appeals**: Board of Tax Appeals, Public Utilities Commission, Power Siting Board
- **Certified Conflicts**: Conflicting appellate court decisions
- **Certified Questions**: Questions of state law from federal courts
- **Election Cases**: Contest of election, expedited election matters
- **Bar Admissions**: Character and fitness cases

---

## Opinion Types and Publication

### Case Disposition Types
- Merit decisions with opinions
- Merit decisions without opinions
- Motion and procedural rulings
- Appeals accepted for review
- Appeals not accepted for review
- Disciplinary cases
- Administrative actions
- Official versions released

### Daily Announcements
- Published daily when Court is in session
- Include case summaries, slip opinions, and procedural orders
- Available via GovDelivery email subscription
- Archive available at: https://www.supremecourt.ohio.gov/opinions-cases/daily-archive/

---

## Access Restrictions

### No Login Required
- All Supreme Court and Courts of Appeals opinions
- Opinion search and filtering
- Docket search (cases from 1985+, practice of law from 1989+)
- Case information pages
- Justice biographies
- Oral argument videos (via Ohio Channel)
- Daily case announcements

### Login Required
- E-Filing system (attorneys and parties)
- Case Activity Notification service (free registration)

### Rate Limiting
- No apparent CAPTCHA or aggressive rate limiting observed
- Standard best practices recommended for scraping

---

## Oral Arguments

### Live Streaming and Archives
- **Ohio Channel**: https://ohiochannel.org/series/supreme-court-of-ohio
- Oral arguments are broadcast live and archived
- Searchable by keyword and date range

### Calendar
- **URL**: https://www.supremecourt.ohio.gov/opinions-cases/oral-arguments/oral-argument-calendar/
- Shows upcoming oral argument schedule

### Case Docket Links
- Oral argument recordings linked from individual case docket pages
- "Click to watch oral argument" link when available

---

## Technical Implementation Notes

### Website Architecture
- **Primary Domain**: www.supremecourt.ohio.gov
- **Docket System**: Ember.js single-page application
- Opinion search is a traditional ASP.NET WebForms application
- PDF viewer application for document display

### Opinion Search System
- ASP.NET WebForms application
- Supports full-text search of opinion content
- Results sortable by: Case Caption, Case No., Topics and Issues, Author, Citation/County, Decided Date, Posted Date, WebCite
- Results per page: 5, 10, 25, 50, 100, 200

### Docket System (ECMS)
- Ember.js single-page application
- Hash-based routing (URLs use `#/`)
- AJAX-loaded content
- Case search supports: Case Number, Case Caption, Prior Case Number, Prior Jurisdiction, Case Type, Filed Between dates
- Party and Attorney search available

### Scraping Approach
1. **Recent Opinions**: Use Opinion Search with date filters
   - URL: `https://www.supremecourt.ohio.gov/Rod/docs/Default.aspx`
   - Filter by year and source
2. **Historical Data**: Paginate through opinion search results (opinions available from 1992+)
3. **Docket Information**: Use ECMS docket system (cases from 1985+)
4. **Courts of Appeals**: Filter opinion search by source (1-12)

### Data Availability
- **Opinions**: Available from 1992 to present
- **Docket Information**: Supreme Court cases from January 1, 1985+
- **Practice of Law Cases**: From January 1, 1989+
- **Oral Arguments**: Archived on Ohio Channel

---

## Example URLs

```
# Opinion search main page
GET https://www.supremecourt.ohio.gov/Rod/docs/Default.aspx

# Opinion search - Supreme Court 2026
GET https://www.supremecourt.ohio.gov/Rod/docs/?source=0

# Opinion search - First District Court of Appeals
GET https://www.supremecourt.ohio.gov/Rod/docs/?source=1

# Individual Supreme Court opinion PDF
GET https://www.supremecourt.ohio.gov/rod/docs/pdf/0/2026/2026-Ohio-148.pdf

# Case docket page
GET https://www.supremecourt.ohio.gov/Clerk/ecms/#/caseinfo/2024/0749

# Case search page
GET https://www.supremecourt.ohio.gov/Clerk/ecms/#/search

# Issues accepted for review
GET https://www.supremecourt.ohio.gov/Clerk/ecms/#/issues

# Justices overview page
GET https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/

# Individual justice bio
GET https://www.supremecourt.ohio.gov/courts/judicial-system/supreme-court-of-ohio/justices-overview/sharon-kennedy/

# Oral argument calendar
GET https://www.supremecourt.ohio.gov/opinions-cases/oral-arguments/oral-argument-calendar/

# Ohio Channel oral arguments
GET https://ohiochannel.org/series/supreme-court-of-ohio
```

---

## Example Cases

### Recent Supreme Court Cases (January 2026)
- **State v. McAlpin** - 2026-Ohio-148 (Docket 2024-0749) - Death Penalty Postconviction Case
- **Sauter v. Integrity Cycles, L.L.C.** - 2026-Ohio-88 (Docket 2024-0370) - Saving statute case
- **Jones Apparel Group/Nine West Holdings v. Harris** - 2026-Ohio-74 (Docket 2023-1288) - Commercial activity tax
- **State ex rel. Boddy v. Xenia Community City School Dist. Bd. of Edn.** - 2026-Ohio-164 (Docket 2025-0262) - Public records
- **Disciplinary Counsel v. Celebrezze** - 2026-Ohio-45 (Docket 2025-1005) - Judge misconduct

---

## Contact Information

### Supreme Court of Ohio
- **Phone**: 614.387.9000
- **TTY**: 614.387.9404
- **Address**: 65 S. Front Street, Columbus, OH 43215-3431
- **Hours**: Monday – Friday, 8:00 AM – 5:00 PM

### Office of Clerk of the Court
- **Clerk**: Robert Vaughn
- **Phone**: 800.826.9010 or 614.387.9530
- **Address**: 65 South Front Street, 8th Floor, Columbus, Ohio 43215-3431

### Court News
- **Court News Ohio**: https://www.courtnewsohio.gov/
- Provides case summaries, news, and analysis

### Social Media
- **YouTube**: https://www.youtube.com/courtnewsohiotv
- **Twitter/X**: https://twitter.com/OHSupremeCourt
- **Facebook**: https://www.facebook.com/OhioSupremeCourt
- **Instagram**: https://www.instagram.com/ohiosupremecourt/
- **LinkedIn**: https://www.linkedin.com/company/supreme-court-of-ohio

---

## Notes

1. **Large Court System**: Ohio has one of the larger state court systems with 12 appellate districts covering 88 counties.

2. **Unified Opinion Database**: The opinion search system includes opinions from all 12 Courts of Appeals plus the Supreme Court, searchable from a single interface.

3. **Two Search Systems**: Opinions are searched via the Reporter of Decisions system (Rod/docs), while docket/case information is searched via the Clerk's ECMS system.

4. **WebCite System**: Ohio uses a unique citation format (YYYY-Ohio-NNN) that serves as both a citation and a direct lookup key.

5. **E-Filing**: Ohio has mandatory e-filing for attorneys. The Supreme Court e-filing system is separate from trial court systems.

6. **Daily Announcements**: The Court publishes daily announcements that include all decisions, orders, and case acceptances/denials.

7. **Ohio Channel Partnership**: Oral arguments are broadcast via the Ohio Channel, a service of Ohio's public broadcasting stations.

8. **Historical Data**: Opinion database goes back to 1992; docket database goes back to 1985.

9. **Court of Claims**: A separate Court of Claims handles civil actions against the state, with its own website at ohiocourtofclaims.gov.

10. **Prior Jurisdiction Tracking**: The docket system tracks which lower court the case came from, useful for understanding the appeal chain.
