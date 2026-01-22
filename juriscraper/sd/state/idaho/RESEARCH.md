# Idaho Courts Research

## Court Structure

Idaho has a two-tier appellate court system with the Idaho Supreme Court at the apex and the Idaho Court of Appeals as the intermediate appellate court.

### 1. Idaho Supreme Court
- **Website**: https://isc.idaho.gov/
- Highest court in Idaho
- 5 Justices (1 Chief Justice + 4 Associate Justices)
- Justices are initially appointed by the Governor, then face nonpartisan retention elections
- 6-year terms
- Location: 451 W. State St, Boise, ID 83702

### 2. Idaho Court of Appeals
- **Website**: https://isc.idaho.gov/ (same website)
- Intermediate appellate court
- 4 Judges (1 Chief Judge + 3 Associate Judges)
- Created in 1982
- Hears most appeals from district courts
- Decisions may be appealed to the Supreme Court

---

## Key URLs and URL Patterns

### Main Portal
- **Home**: https://isc.idaho.gov/
- **Opinions Main Page**: https://isc.idaho.gov/appeals-court/opinions
- **Supreme Court Civil Opinions**: https://isc.idaho.gov/appeals-court/isc_civil
- **Supreme Court Criminal Opinions**: https://isc.idaho.gov/appeals-court/isc_criminal
- **Court of Appeals Civil Opinions**: https://isc.idaho.gov/appeals-court/coa_civil
- **Court of Appeals Criminal & PC Opinions**: https://isc.idaho.gov/appeals-court/coa_criminal
- **Court of Appeals Unpublished Opinions**: https://isc.idaho.gov/appeals-court/coaunpublished
- **Court of Appeals Unpublished Per Curiam Opinions**: https://isc.idaho.gov/appeals-court/Unpublished-Per-Curiam

### Oral Arguments
- **Supreme Court Calendar**: https://isc.idaho.gov/appeals-court/isc-calendar
- **Court of Appeals Calendar**: https://isc.idaho.gov/appeals-court/coa-calendar
- **ISC Hearings Video Archive**: https://isc.idaho.gov/appeals-court/archive
- **Court of Appeals Hearings Archive**: https://isc.idaho.gov/appeals-court/court-of-appeals-archive
- **Live Stream**: http://idahoptv.org/insession/courts.cfm (Idaho Public Television)

### Case Search (iCourt Portal)
- **Portal Home**: https://mycourts.idaho.gov/odysseyportal (redirects to https://portal-idaho.tylertech.cloud/odysseyportal)
- **Smart Search**: https://portal-idaho.tylertech.cloud/odysseyportal/Home/Dashboard/29
- **Search Hearings**: https://portal-idaho.tylertech.cloud/odysseyportal/Home/Dashboard/26
- Powered by Tyler Technologies Odyssey system
- Covers all Idaho counties

### Court Information
- **Judicial Directory (PDF)**: http://isc.idaho.gov/files/judicial_directory.pdf
- **Terms of Office**: https://sos.idaho.gov/elections-division/elected-officials/
- **Contact - Courts of Appeal**: https://isc.idaho.gov/main/contactus

---

## Opinion PDF URL Patterns

### Supreme Court and Court of Appeals Opinions
- `https://isc.idaho.gov/opinions/{docket_number}.pdf`
- `https://isc.idaho.gov/opinions/{docket_number}summ.pdf` (summary)

### Examples
- Opinion: https://isc.idaho.gov/opinions/51532.pdf
- Summary: https://isc.idaho.gov/opinions/51532summ.pdf
- Opinion: https://isc.idaho.gov/opinions/52011.pdf
- Summary: https://isc.idaho.gov/opinions/52011summ.pdf

### Docket Number Format
- Simple 5-digit numbers (e.g., 51532, 52011, 53264)
- Some may have letter suffixes (e.g., 52032c.pdf)
- Numbers appear to be sequential across all courts

---

## Current Justices - Idaho Supreme Court

| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| G. Richard Bevan | Chief Justice (43rd) | Sept 1, 2017 | https://isc.idaho.gov/main/Bevan |
| Robyn M. Brody | Vice Chief Justice | Nov 2016 (elected) | https://isc.idaho.gov/main/Brody |
| Gregory W. Moeller | Associate Justice (58th) | Jan 3, 2019 | https://isc.idaho.gov/justice-moeller |
| Colleen D. Zahn | Associate Justice (59th) | July 1, 2021 | https://isc.idaho.gov/justice-zahn |
| Cynthia K.C. Meyer | Associate Justice (60th) | Nov 6, 2023 | https://isc.idaho.gov/Cynthia-Meyer |

---

## Current Judges - Idaho Court of Appeals

| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Michael P. Tribe | Chief Judge | Jan 23, 2024 | https://isc.idaho.gov/m_tribe |
| David W. Gratton | Associate Judge | - | https://isc.idaho.gov/main/w-gratton |
| Molly J. Huskey | Associate Judge | - | https://isc.idaho.gov/main/m_huskey |
| Jessica M. Lorello | Associate Judge | - | https://isc.idaho.gov/main/j_lorello |

**Note**: The website navigation lists Chief Judge Jessica M. Lorello but the sidebar and bio pages indicate Michael P. Tribe is the current Chief Judge (appointed Jan 2024). There may be recent retirements announced per press release dated Jan 7, 2026.

---

## Jurisdiction

### Idaho Supreme Court
- Final appellate jurisdiction over all cases decided by the Court of Appeals
- Original jurisdiction in habeas corpus proceedings
- Original jurisdiction in claims against the state
- Administrative supervision of all courts in the state
- Admission and discipline of attorneys
- Promulgation of court rules

### Idaho Court of Appeals
- Appellate jurisdiction assigned by the Supreme Court
- Hears most appeals from district courts
- Criminal appeals (except death penalty cases)
- Civil appeals
- Post-conviction relief appeals
- Decisions reviewable by Supreme Court

---

## Opinion Types and Publication

### Opinion Categories
1. **Supreme Court Civil Opinions**: Civil cases heard by the Supreme Court
2. **Supreme Court Criminal Opinions**: Criminal cases heard by the Supreme Court
3. **Court of Appeals Civil Opinions**: Civil appeals to the Court of Appeals
4. **Court of Appeals Criminal & Post-Conviction Opinions**: Criminal and post-conviction appeals
5. **Court of Appeals Unpublished Opinions**: Non-precedential decisions
6. **Court of Appeals Unpublished Per Curiam Opinions**: Unsigned non-precedential decisions

### Publication
- Cited opinions are published in:
  - Pacific Reporter (West Publishing)
  - Idaho Reports
- Opinions are posted on the day of release
- Summaries are prepared by court staff (not part of the official opinion)

---

## Access Restrictions

### No Login Required
- Public access to all published opinions
- Oral argument schedules and videos
- Judge biographies

### iCourt Portal Access Levels
- **Basic Public Access**: Free, limited case information
- **Extended Access**: Available to federal, state, and local officials for official duties
- **Sealed Cases**: Not visible in public search (per ICAR Rule 32)

### Data Availability
- Opinions available on website (historical depth unclear, appears extensive)
- Case search covers all Idaho counties
- Video archives of oral arguments on YouTube

---

## Technical Implementation Notes

### Website Platform
- Drupal-based website (based on URL patterns and structure)
- Opinions stored in `/opinions/` directory
- Static HTML pages for opinion listings

### Opinion URL Structure
- Direct PDF links: `/opinions/{docket_number}.pdf`
- Summary PDFs: `/opinions/{docket_number}summ.pdf`
- Docket numbers are 5-digit integers
- Some opinions have letter suffixes (e.g., `c` for corrected/consolidated)

### iCourt Portal
- Tyler Technologies Odyssey system
- Requires JavaScript for full functionality
- Session-based with 20-minute idle timeout
- Supports "Smart Search" and hearing search

### Oral Arguments
- Live streaming via Idaho Public Television
- Archived recordings on YouTube
- Calendar available as PDF downloads (Spring/Fall terms)

### Scraping Considerations
- Drupal CMS with predictable URL patterns
- Opinion listing pages appear to be static HTML
- PDF files directly accessible
- No apparent rate limiting, but respectful scraping recommended
- iCourt Portal would require JavaScript handling

---

## Example Cases

### Supreme Court
- **#53264** - Committee to Protect & Preserve v. State (oral argument Jan 23, 2026)
- **#52584** - WAFD, Inc. v. Idaho State Tax Commission
- **#51866** - State v. Orr
- **#53233** - Best v. State

### Court of Appeals
- Various civil, criminal, and post-conviction cases listed in opinion archives

---

## Recommended Scraper Architecture

### 1. Opinion Listing Scraper
**Source**: Opinion category pages (e.g., https://isc.idaho.gov/appeals-court/isc_civil)

**Approach**:
1. Parse HTML for opinion entries
2. Extract docket numbers and case names
3. Construct PDF URLs using pattern: `/opinions/{docket_number}.pdf`
4. Download both opinion and summary PDFs

**Data Available**:
- Docket number
- Case name/style
- Opinion date
- Court (Supreme Court or Court of Appeals)
- Case type (civil, criminal, post-conviction)
- Publication status (published vs unpublished)
- PDF URL

### 2. Oral Arguments Scraper
**Source**: Calendar pages

**Approach**:
1. Parse calendar pages for scheduled arguments
2. Extract case number, case name, date, time, location
3. Link to video archives via YouTube URLs

### 3. Case Search Integration
**Source**: iCourt Portal (Tyler Odyssey)

**Approach**:
1. Would require Playwright/Selenium for JavaScript rendering
2. Query appellate cases
3. Extract detailed case information
4. Link to opinion PDFs where available

---

## Additional Resources

- **Idaho Appellate Rules**: https://isc.idaho.gov/iar
- **Idaho Court Administrative Rules**: https://isc.idaho.gov/icar
- **Court Rules Index**: https://isc.idaho.gov/main/idaho-court-rules
- **Annual Reports**: https://annualreport.isc.idaho.gov/
- **Email Notification Signup**: https://app.e2ma.net/app2/audience/signup/1992749/1942564/ (for new opinion notices)
- **Cases of Interest**: https://coi.isc.idaho.gov/
- **Idaho State Law Library**: http://www.isll.idaho.gov/

---

## Contact Information

**Clerk of the Idaho Supreme Court & Court of Appeals**
- Phone: (208) 334-2210
- Physical: 451 W. State St, Boise, ID 83702
- Mail: P.O. Box 83720, Boise, ID 83720
