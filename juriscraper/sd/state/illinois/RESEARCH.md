# Illinois Courts Research

## Court Structure

Illinois has a three-tier court system with the Illinois Supreme Court at the apex, followed by the Illinois Appellate Court (with five geographic districts plus Workers' Compensation Commission Division), and Circuit Courts at the trial level.

### 1. Illinois Supreme Court
- **Website**: https://www.illinoiscourts.gov/courts/supreme-court/
- Highest court in Illinois
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- Justices elected in partisan elections for 10-year terms, may be retained for additional 10-year terms
- Chief Justice elected by other justices for a 3-year term
- State divided into 5 judicial districts: 3 justices from First District (Cook County), 1 from each other district
- Location: Illinois Supreme Court Building, Springfield
- Convenes on the second Monday of September, November, January, March, and May

### 2. Illinois Appellate Court
- **Website**: https://www.illinoiscourts.gov/courts/appellate-court/
- Intermediate appellate court
- Currently 54 judgeships (set by legislature)
- Organized into 5 geographic districts plus Workers' Compensation Commission Division
- Judges elected by voters in each district for 10-year terms

#### Appellate Court Districts:
| District | Location | Divisions |
|----------|----------|-----------|
| First District | Chicago | 6 divisions |
| Second District | Elgin | 1 division |
| Third District | Ottawa | 1 division |
| Fourth District | Springfield | 1 division |
| Fifth District | Mount Vernon | 1 division |
| Workers' Compensation | - | - |

---

## Key URLs and URL Patterns

### Main Portal
- **Home**: https://www.illinoiscourts.gov/
- **Opinions Main Page**: https://www.illinoiscourts.gov/top-level-opinions/
- **Supreme Court Opinions**: https://www.illinoiscourts.gov/top-level-opinions?type=supreme
- **Appellate Court Opinions**: https://www.illinoiscourts.gov/top-level-opinions?t=appellate

### Opinion URL Patterns
- **Opinions Search**: https://www.illinoiscourts.gov/top-level-opinions?type={court}
  - `type=supreme` - Supreme Court
  - `type=appellate1` - First District Appellate (assumed pattern)
  - Filter options: Court, Decision Type (Opinion/Rule 23), Status (Slip/Released/Final), Date Range

### RSS Feeds
- **Supreme Court Opinions**: https://www.illinoiscourts.gov/views/courts/rss/opinions-supreme.aspx
- **Appellate Court Opinions**: https://www.illinoiscourts.gov/views/courts/rss/opinions-appellate.aspx

### Opinion PDF URLs
- **Pattern**: `https://www.illinoiscourts.gov/resources/{guid}/file`
- **Summary PDFs**: `https://ilcourtsaudio.blob.core.windows.net/antilles-resources/resources/{guid}/{case-name} Sum.pdf`

### Briefs and Docket
- **Docket Page**: https://www.illinoiscourts.gov/courts/supreme-court/docket/
- **Briefs Pattern**: `https://ilcourtsaudio.blob.core.windows.net/antilles-resources/resources/{guid}/{case-number} {case-name} {brief-type}.pdf`
  - Brief types: ATB (Appellant's Brief), AEB (Appellee's Brief), RPB (Reply Brief), AMB (Amici Brief), XRB (Cross Reply Brief)
- **Call of the Docket**: `https://ilcourtsaudio.blob.core.windows.net/antilles-resources/resources/{guid}/{Month Year}.pdf`
- **Docket Book**: `https://ilcourtsaudio.blob.core.windows.net/antilles-resources/resources/{guid}/{Month Year} Docket Book.pdf`

### Court Information
- **Supreme Court Justices**: https://www.illinoiscourts.gov/courts/supreme-court/meet-the-justices/
- **Appellate Court Justices by District**: https://www.illinoiscourts.gov/courts/circuit-court/chief-judges-and-administrative-staff/?t=appellate&d={1-5}
- **Oral Argument Audio/Video**: https://www.illinoiscourts.gov/courts/supreme-court/oral-argument-audio-and-video/
- **Oral Arguments Calendar**: https://www.illinoiscourts.gov/courts/appellate-court/oral-arguments-calendar/
- **Leave to Appeal Dispositions**: https://www.illinoiscourts.gov/courts/supreme-court/leave-to-appeal/

### Case Search (Re:SearchIL)
- **Portal**: https://researchil.tylerhost.net/CourtRecordsSearch/Home#/home
- Powered by Tyler Technologies
- Statewide document repository for eFileIL documents

---

## Citation Format

### Illinois Supreme Court
- Format: `YYYY IL XXXXXX`
- Example: `2025 IL 131564`
- Where XXXXXX is the case number

### Illinois Appellate Court
- Format: `YYYY IL App (Xd) XXXXXX`
- Example: `2025 IL App (1st) 240123`
- X = District number (1st, 2d, 3d, 4th, 5th)

---

## Current Justices - Illinois Supreme Court

| Name | Position | District | Term/Appointment |
|------|----------|----------|------------------|
| P. Scott Neville, Jr. | Chief Justice | First (Cook County) | Appointed June 15, 2018; elected Nov. 3, 2020 |
| Mary Jane Theis | Justice | First (Cook County) | - |
| David K. Overstreet | Justice | Fifth | - |
| Lisa Holder White | Justice | Fourth | - |
| Joy V. Cunningham | Justice | First (Cook County) | - |
| Elizabeth M. Rochford | Justice | Second | - |
| Mary K. O'Brien | Justice | Third | - |

### Chief Justice P. Scott Neville, Jr. Bio
- Graduate of Washington University School of Law
- Practicing law in Illinois since 1974
- Appointed to Circuit Court of Cook County in 1999
- Appointed to Appellate Court June 11, 2004
- Appointed to Supreme Court June 15, 2018
- Elected to 10-year term November 3, 2020

---

## Jurisdiction

### Illinois Supreme Court
- Final appellate jurisdiction over all cases from the Appellate Court
- Original jurisdiction in certain cases (may be appealed directly from Circuit Court)
- Administrative supervision of all courts in the state
- Admission and discipline of attorneys
- Promulgation of court rules
- Death penalty cases (direct appeal from trial court)

### Illinois Appellate Court
- Appellate jurisdiction over Circuit Court decisions
- Most appeals from Circuit Court go through Appellate Court
- Decisions can be appealed to Supreme Court via Petition for Leave to Appeal

---

## Opinion Types and Publication

### Decision Types
1. **Opinion** - Published, precedential decisions
2. **Rule 23 Order** - Non-precedential orders (per Supreme Court Rule 23)

### Opinion Status
- **Slip** - Initial release
- **Released** - After initial review period
- **Final** - Official, final version

### Publication
- Opinions published in:
  - North Eastern Reporter (West Publishing)
  - Illinois Decisions
  - Official website (illinoiscourts.gov)

---

## Access Restrictions

### No Login Required
- Public access to all published opinions
- Oral argument audio/video
- Docket and briefs
- Judge biographies

### Re:SearchIL Portal
- Free public access to documents filed through eFileIL
- Some documents may be restricted based on case type

### Data Availability
- Opinions available on website with searchable interface
- Historical opinions available (extent unclear)
- RSS feeds for new opinions
- Email notification signup available

---

## Technical Implementation Notes

### Website Platform
- ASP.NET-based website (evidenced by `.aspx` pages and `__doPostBack` JavaScript)
- Uses Azure Blob Storage for document hosting (`ilcourtsaudio.blob.core.windows.net`)
- GUID-based resource URLs

### Opinion Listing Structure
- Searchable table with columns: Case Name, Citation #, Filing Date, Court, Decision Type, Status, Summaries/Notes
- Filterable by: Date range, Court, Decision Type, Status
- Keyword search available
- Results include direct PDF links and summary links

### URL Patterns for Scraping
```
# Opinions page with filters
https://www.illinoiscourts.gov/top-level-opinions?type={court}&t={type}

# Direct opinion PDF (via redirect)
https://www.illinoiscourts.gov/resources/{guid}/file

# Summary PDF (Azure Blob)
https://ilcourtsaudio.blob.core.windows.net/antilles-resources/resources/{guid}/{filename}.pdf

# RSS Feeds
https://www.illinoiscourts.gov/views/courts/rss/opinions-supreme.aspx
https://www.illinoiscourts.gov/views/courts/rss/opinions-appellate.aspx
```

### Scraping Considerations
- No apparent rate limiting
- JavaScript required for search functionality
- RSS feeds available for automated monitoring
- Azure Blob URLs are direct PDF links
- GUID-based URLs require scraping the listing page first

---

## Example Cases

### Supreme Court
- **People v. Seymore** (2025 IL 131564) - Filed 12/04/2025
- **People v. Hietschold** (2025 IL 130716) - Filed 11/20/2025
- **People v. Williams** (2025 IL 130779) - Filed 11/20/2025
- **Fausett v. Walgreen Co.** (2025 IL 131444) - Filed 11/20/2025

### Docket Examples (January 2026 Term)
- Case No. 130932 - People v. Gregory A. Johnson, Jr. (Appeal from Fifth District)
- Case No. 132016 - Lisa Johnson et al. v. Amazon.com Services LLC (Rule 20 Certification)
- Case No. 131240 - People v. Christian L. Shepherd (Appeal from Third District)

---

## Recommended Scraper Architecture

### 1. Opinion Listing Scraper
**Source**: Opinions page with filters

**Approach**:
1. Query opinions page with date range and court filters
2. Parse HTML table for opinion entries
3. Extract: case name, citation, filing date, court, decision type, status
4. Follow PDF links to download opinions
5. Follow summary links for summaries

**Data Available**:
- Case name/style
- Citation number
- Filing date
- Court (Supreme or Appellate District)
- Decision type (Opinion or Rule 23)
- Status (Slip, Released, Final)
- PDF URL
- Summary PDF URL (if available)

### 2. RSS Feed Monitor
**Source**: RSS feeds

**Approach**:
1. Poll RSS feeds periodically
2. Parse new entries for opinion metadata
3. Download new opinions automatically

### 3. Docket/Briefs Scraper
**Source**: Docket page

**Approach**:
1. Parse docket page for case listings
2. Extract case numbers, names, hearing dates
3. Follow brief links to Azure Blob Storage
4. Download briefs by type (Appellant, Appellee, Reply, Amici)

---

## Additional Resources

- **Supreme Court Rules**: https://www.illinoiscourts.gov/rules-law/supreme-court-rules
- **Appellate Court Local Rules**: https://www.illinoiscourts.gov/courts/appellate-court/appellate-court-local-rules/
- **Illinois Rules of Evidence**: https://www.illinoiscourts.gov/courts/supreme-court/courts-supreme-court-illinois-rules-of-evidence/
- **Style Manual**: https://ilcourtsaudio.blob.core.windows.net/antilles-resources/resources/dda02046-19c4-4908-a41e-2bec79de43cf/Style%20Manual%20for%20the%20Supreme%20and%20Appellate%20Court.pdf
- **Caseload Statistics**: https://www.illinoiscourts.gov/courts/supreme-court/supreme-court-caseload-statistics/
- **Email Notification Signup**: https://www.illinoiscourts.gov/email-lists/subscribe

---

## Contact Information

**Illinois Supreme Court Clerk**
- Website: https://www.illinoiscourts.gov/courts/supreme-court/staff-and-contact-information/

**Administrative Office of the Illinois Courts (AOIC)**
- Website: https://www.illinoiscourts.gov/aoic/
- Contact: https://www.illinoiscourts.gov/aoic/contact/
