# Nebraska Courts Research

## Court Structure

Nebraska has a two-tier appellate court system:

### 1. Nebraska Supreme Court
- **Website**: https://nebraskajudicial.gov/courts/supreme-court
- Highest court in the state
- 7 Justices (1 Chief Justice + 6 Associate Justices from 6 districts)
- Chief Justice represents the state at large
- Associate justices represent approximately equal population districts
- Justices appointed by Governor from judicial nominating commission list
- Retained through nonpartisan elections
- Located in State Capitol, Lincoln, Nebraska

#### Jurisdiction
- Appeals from Court of Appeals (via Petition for Further Review)
- Direct appeals in death penalty and life imprisonment cases
- Constitutional questions
- Regulation of practice of law/attorney discipline
- Administrative leadership of state judicial system

### 2. Nebraska Court of Appeals
- **Website**: https://nebraskajudicial.gov/courts/court-appeals
- Intermediate appellate court (established 1991)
- 6 Judges (1 Chief Judge + 5 Judges)
- Appointed from same 6 districts as Supreme Court justices
- Chief Judge serves 2-year renewable term
- Divided into two 3-judge panels
- Primary courtroom in State Capitol, Lincoln
- Travels to other Nebraska cities for hearings

#### Jurisdiction
- All appeals except death penalty, life imprisonment, and constitutional questions
- Cases can be moved to Supreme Court via petition to bypass or petition for further review

### 3. Trial Courts (for reference)
- **District Courts**: General jurisdiction (93 counties, 12 judicial districts)
- **County Courts**: Limited jurisdiction (93 courts)
- **Separate Juvenile Courts**: Douglas, Lancaster, and Sarpy Counties
- **Workers' Compensation Court**: Statewide

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://nebraskajudicial.gov/
- **Courts Overview**: https://nebraskajudicial.gov/courts
- **Supreme Court**: https://nebraskajudicial.gov/courts/supreme-court
- **Court of Appeals**: https://nebraskajudicial.gov/courts/court-appeals

### Opinion Libraries

#### Judicial Branch Website (Recent - Last 90 Days)
- **Supreme Court Opinions**: https://nebraskajudicial.gov/courts/supreme-court/supreme-court-opinions
  - Organized by date with tables showing: Case Number, Cite As, Title/Download PDF
  - Links directly to Online Library for full opinions

- **Court of Appeals Opinions**: https://nebraskajudicial.gov/courts/court-appeals/court-appeals-opinions
  - Organized by date
  - Shows both published Opinions and Memorandum Opinions
  - Published opinions link to Online Library
  - Memorandum opinions link to PDFs on judicial branch site

#### Nebraska Appellate Courts Online Library (Full Archive)
- **Main Portal**: https://www.nebraska.gov/apps-courts-epub/
- **Supreme Court**: https://www.nebraska.gov/apps-courts-epub/public/supreme
- **Court of Appeals**: https://www.nebraska.gov/apps-courts-epub/public/appeals

##### Opinion URL Patterns
- **View Individual Opinion**: `https://www.nebraska.gov/apps-courts-epub/public/viewOpinion?docId={DOC_ID}PUB`
  - Example: `https://www.nebraska.gov/apps-courts-epub/public/viewOpinion?docId=N00012939PUB`
- **View Volume PDF**: `https://www.nebraska.gov/apps-courts-epub/public/viewVolume?docId={DOC_ID}PUB`
- **Memorandum List**: `https://www.nebraska.gov/apps-courts-epub/public/viewMemo?docId={DOC_ID}PUB`
- **Disposed Without Opinion**: `https://www.nebraska.gov/apps-courts-epub/public/viewDWO?docId={DOC_ID}PUB`
- **Petition for Further Review**: `https://www.nebraska.gov/apps-courts-epub/public/viewPFR?docId={DOC_ID}PUB`
- **Pagination**: `?offset={N}&max=25`

##### Memorandum Opinions (Non-Published)
- **URL Pattern**: `https://nebraskajudicial.gov/sites/default/files/memorandums/{case_number}m.pdf`
  - Example: `https://nebraskajudicial.gov/sites/default/files/memorandums/a24-927m.pdf`
- **Multiple cases**: `{case_number}mm.pdf`
  - Example: `https://nebraskajudicial.gov/sites/default/files/memorandums/a25-205mm.pdf`
- **Not posted list**: `https://nebraskajudicial.gov/sites/default/files/memorandums/NonWeblist{date}.pdf`

### Case Search
- **Case Information Portal**: https://www.nebraska.gov/justice
- **One-Time Trial Court Search**: https://www.nebraska.gov/justicecc/ccname.cgi ($17 per search)
- **Subscriber Account Search**: https://www.nebraska.gov/justice/name.cgi
- **Case Number Search**: https://www.nebraska.gov/justice/case.cgi ($2 per case)
- **Judgment Date Search**: https://www.nebraska.gov/courts/jcs/index.cgi ($2 per case)

Note: Appellate case searches require a subscriber account through Nebraska.gov ($100/year) and cost $1 per case detail view.

### Oral Arguments
- **Supreme Court Archive**: https://nebraskajudicial.gov/courts/supreme-court/supreme-court-oral-argument-archive
- **Court of Appeals Archive**: https://nebraskajudicial.gov/courts/court-appeals/court-appeals-oral-argument-archive
- **Live Stream**: https://nebraskapublicmedia.org/en/watch/live/
- Audio and video available within 24 hours of arguments
- Archives include case summaries, case numbers, county, and audio files

### Judge/Justice Pages
- **Supreme Court Justices**: https://nebraskajudicial.gov/courts/supreme-court/supreme-court-justices
- **Court of Appeals Judges**: https://nebraskajudicial.gov/courts/court-appeals/court-appeals-judges
- **Individual Bio Pattern**: `https://nebraskajudicial.gov/courts/hon-{first-name}-{middle-initial}-{last-name}` or similar

---

## Current Justices - Nebraska Supreme Court

| Name | Position | District | Bio URL |
|------|----------|----------|---------|
| Hon. Jeffrey J. Funke | Chief Justice | At Large | https://nebraskajudicial.gov/courts/hon-jeffrey-j-funke-chief-justice |
| Hon. Stephanie F. Stacy | Associate Justice | 1 | https://nebraskajudicial.gov/courts/hon-stephanie-f-stacy |
| Hon. Derek R. Vaughn | Associate Justice | 2 | https://nebraskajudicial.gov/courts/hon-derek-r-vaughn |
| Hon. William B. Cassel | Associate Justice | 3 | https://nebraskajudicial.gov/courts/hon-william-b-cassel |
| Hon. Jonathan J. Papik | Associate Justice | 4 | https://nebraskajudicial.gov/courts/hon-jonathan-j-papik |
| Hon. Jason M. Bergevin | Associate Justice | 5 | https://nebraskajudicial.gov/courts/hon-jason-m-bergevin |
| Hon. John R. Freudenberg | Associate Justice | 6 | https://nebraskajudicial.gov/courts/hon-john-r-freudenberg |

**Notes**:
- Chief Justice Funke: Previously Justice in 5th District (2016-2024), became Chief Justice 2024
- All justices located in State Capitol, Lincoln, NE 68509

---

## Current Judges - Nebraska Court of Appeals

| Name | Position | District | Bio URL |
|------|----------|----------|---------|
| Hon. Francie C. Riedmann | Chief Judge | 3 | https://nebraskajudicial.gov/courts/hon-francie-c-riedmann-chief-judge |
| Hon. Riko Bishop | Judge | 1 | https://nebraskajudicial.gov/courts/hon-riko-bishop |
| Hon. Michael W. Pirtle | Judge | 2 | https://nebraskajudicial.gov/courts/hon-michael-w-pirtle |
| Hon. PaTricia Freeman | Judge | 4 | https://nebraskajudicial.gov/courts/hon-patricia-freeman |
| Hon. Lawrence E. Welch, Jr. | Judge | 5 | https://nebraskajudicial.gov/courts/hon-lawrence-e-welch-jr |
| Hon. Frankie J. Moore | Judge | 6 | https://nebraskajudicial.gov/courts/hon-frankie-j-moore |

---

## Case Number Format

### Supreme Court
- **Pattern**: `S-{YY}-{NNNN}`
- **Examples**:
  - `S-24-295` - Case from 2024
  - `S-25-137` - Case from 2025 (can have ranges like `S-25-137 through S-25-141`)

### Court of Appeals
- **Pattern**: `A-{YY}-{NNN}` or `A-{YY}-{NNNN}`
- **Examples**:
  - `A-24-927` - Case from 2024
  - `A-25-239` - Case from 2025

### Citation Format
- **Supreme Court**: `{Vol} Neb. {Page}` (e.g., `320 Neb. 675`)
- **Court of Appeals**: `{Vol} Neb. App. {Page}` (e.g., `34 Neb. App. 1`)

---

## Opinion Types and Publication

### Supreme Court
- **Published Opinions**: Full written decisions with volume/page citations
- **Memorandum Opinions**: Non-precedential, filed separately
- **Disposed Without Opinion (DWO)**: Cases resolved without written opinion
- **Release Schedule**: 8:00 AM on Fridays

### Court of Appeals
- **Published Opinions**: Precedential decisions with citations
- **Memorandum Opinions**: Non-precedential, available as PDFs
- **Disposed Without Opinion (DWO)**: Cases resolved without written opinion
- **Petition for Further Review (PFR)**: Cases pending Supreme Court review
- **Release Schedule**: 8:00 AM on Tuesdays

### Volume Organization
- Opinions organized by volume number (e.g., `320 Neb.`, `34 Neb. App.`)
- Each volume has opening and closing date range
- Volumes include links to Memo, DWO, and PFR lists

---

## Access Restrictions

### No Login Required
- Judicial branch website (nebraskajudicial.gov)
- Online Opinion Library (nebraska.gov/apps-courts-epub)
- Recent opinions on judicial branch site
- Justice/Judge biography pages
- Oral argument archives (audio/video)
- Supreme Court rules

### Subscriber Account Required ($100/year)
- Appellate case detail searches via SCCALES
- Trial court case searches via JUSTICE
- Individual case views: $1-2 per case

### Free Public Access Locations
- Any courthouse kiosk
- Nebraska State Library
- UNL Schmid Law Library
- Creighton Klutznick Law Library

### Rate Limiting
- No obvious rate limiting observed
- Standard web scraping best practices recommended

---

## Oral Arguments

### Schedule and Access
- Live streaming via Nebraska Public Media
- Audio uploaded within 24 hours
- Video available for full sessions
- Archive searchable by month/year

### Archive Content
- Case title (linked to case summary)
- Case number
- County of origin
- Audio player for each case
- Video link for full session

---

## Technical Implementation Notes

### Website Structure
- **Primary Domain**: nebraskajudicial.gov (Drupal-based)
- **Online Library**: nebraska.gov/apps-courts-epub (separate application)
- **Case Management Systems**:
  - JUSTICE: Trial courts
  - SCCALES: Appellate courts

### Opinion Scraping Approach

#### Supreme Court
1. **Recent (90 days)**: Parse tables at `/courts/supreme-court/supreme-court-opinions`
   - Each row has date, case number, citation, title with link to opinion
2. **Full Archive**: Use `/apps-courts-epub/public/supreme`
   - Navigate volumes, expand to see individual opinions
   - Download PDFs via `viewOpinion?docId=` URLs

#### Court of Appeals
1. **Recent (90 days)**: Parse tables at `/courts/court-appeals/court-appeals-opinions`
   - Includes both published opinions and memorandum opinions
   - Memorandum opinions stored as PDFs on judicial branch site
2. **Full Archive**: Use `/apps-courts-epub/public/appeals`
   - Similar structure to Supreme Court

### PDF Downloads
- Opinions available as individual PDFs via docId
- Older volumes available as full PDF downloads
- All documents in PDF format requiring Adobe Reader or equivalent

### Search Functionality
- Online Library has search box: "Search All Opinions"
- Free text search across all published opinions

### Example API-like Calls
```
# Recent Supreme Court Opinions
GET https://nebraskajudicial.gov/courts/supreme-court/supreme-court-opinions

# Recent Court of Appeals Opinions
GET https://nebraskajudicial.gov/courts/court-appeals/court-appeals-opinions

# Online Library - Supreme Court Volumes
GET https://www.nebraska.gov/apps-courts-epub/public/supreme

# Online Library - Court of Appeals Volumes
GET https://www.nebraska.gov/apps-courts-epub/public/appeals

# View Individual Opinion
GET https://www.nebraska.gov/apps-courts-epub/public/viewOpinion?docId=N00012939PUB

# Memorandum Opinion PDF
GET https://nebraskajudicial.gov/sites/default/files/memorandums/a24-927m.pdf

# Oral Argument Archive
GET https://nebraskajudicial.gov/courts/supreme-court/supreme-court-oral-argument-archive
```

---

## Example Cases

### Supreme Court - State v. Cartwright (S-24-295)
- **Citation**: 320 Neb. 619
- **Filed**: January 9, 2026
- **Opinion URL**: https://www.nebraska.gov/apps-courts-epub/public/viewOpinion?docId=N00012924PUB

### Supreme Court - In re Interest of Johnny H. (S-25-137 through S-25-141)
- **Citation**: 320 Neb. 675
- **Filed**: January 16, 2026
- **Opinion URL**: https://www.nebraska.gov/apps-courts-epub/public/viewOpinion?docId=N00012939PUB

### Court of Appeals - State v. Kuol (A-25-239)
- **Citation**: 34 Neb. App. 1
- **Filed**: January 20, 2026
- **Opinion URL**: https://www.nebraska.gov/apps-courts-epub/public/viewOpinion?docId=N00012943PUB

---

## Contact Information

### Reporter of Decisions
- **Phone**: 402-471-3010
- **Email**: nsc.reportersoffice.elibrary@nejudicial.gov
- **Contact Page**: https://www.nebraska.gov/apps-courts-epub/public/contactUs

### Clerk of the Supreme Court
- Located in State Capitol, Lincoln, NE

### General Contact
- **Website**: https://nebraskajudicial.gov/contact

---

## Notes

1. **Court of Appeals Established 1991**: Nebraska's intermediate appellate court is relatively recent compared to some states.

2. **Two Panel System**: Court of Appeals operates in two 3-judge panels to expedite case processing.

3. **Petition for Further Review**: After Court of Appeals decision, parties can petition Supreme Court for review. If granted, case moves to Supreme Court.

4. **Petition to Bypass**: Parties can petition to bypass Court of Appeals and go directly to Supreme Court in certain cases.

5. **Memorandum Opinions**: Non-precedential opinions available for Court of Appeals, stored as PDFs on judicial branch site with specific naming conventions.

6. **Paid Case Search**: Unlike opinions, detailed case information requires paid subscriber access ($100/year + per-case fees).

7. **Publication Schedule**:
   - Supreme Court: Fridays at 8 AM
   - Court of Appeals: Tuesdays at 8 AM

8. **Historical Coverage**:
   - Supreme Court: Volumes go back to at least 1997 (296 Neb.)
   - Court of Appeals: Volumes go back to at least 1992 (1 Neb. App.)

9. **Document IDs**: Opinion docIds follow pattern like `N00012939PUB` - numeric ID with PUB suffix.

10. **Existing Scraper**: Check juriscraper opinions directory for existing Nebraska scrapers.
