# New Jersey Courts Research

## Court Structure

New Jersey has a unified statewide court system with the following appellate hierarchy:

### 1. New Jersey Supreme Court
- **Website**: https://www.njcourts.gov/courts/supreme
- Highest court in New Jersey
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- Justices nominated by the Governor, confirmed by the Senate
- Initial 7-year term; if reappointed, tenure until age 70
- Located at Richard J. Hughes Justice Complex, Trenton, NJ

#### Jurisdiction
- Final appellate court for all state courts
- Reviews cases primarily through certification (discretionary)
- Direct appeals as of right when Appellate Division judge dissents
- Interprets NJ Constitution, US Constitution as applied in NJ, NJ statutes, and administrative regulations
- Chief Justice is administrative head of entire court system

### 2. Appellate Division of Superior Court
- **Website**: https://www.njcourts.gov/courts/appellate
- Intermediate appellate court
- 32 judges divided into 8 parts
- Hears ~6,500 appeals and 10,000 motions per year
- Arguments held in Morristown, New Brunswick, Newark, and Trenton
- Cases decided by 2- or 3-judge panels

### 3. Tax Court
- **Website**: https://www.njcourts.gov/courts/tax
- Statewide forum for tax appeals
- Appeals from county boards of taxation and state agency decisions

### 4. Superior Court (Trial Court)
- **Website**: https://www.njcourts.gov/courts/vicinages
- General jurisdiction trial court
- Organized into 15 vicinages (judicial districts) covering 21 counties
- Three divisions: Civil, Criminal, Family

### 5. Municipal Court
- **Website**: https://www.njcourts.gov/courts/municipal
- Limited jurisdiction (traffic, minor criminal, municipal ordinances)
- Over 500 municipal courts statewide

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://www.njcourts.gov/
- **Courts Overview**: https://www.njcourts.gov/courts
- **Attorneys Section**: https://www.njcourts.gov/attorneys

### Supreme Court
- **Supreme Court Home**: https://www.njcourts.gov/courts/supreme
- **About/Justices**: https://www.njcourts.gov/courts/supreme/about
- **Argument Schedule**: https://www.njcourts.gov/courts/supreme/arguments
- **Supreme Court Appeals**: https://www.njcourts.gov/courts/supreme/appeals
- **Webcast**: https://www.njcourts.gov/courts/supreme/supreme-court-webcast
- **Recent Arguments Archive**: https://www.njcourts.gov/courts/supreme/supreme-court-webcast/recent-arguments

### Court Opinions
- **Opinions Main**: https://www.njcourts.gov/attorneys/opinions
- **Supreme Court Opinions**: https://www.njcourts.gov/attorneys/opinions/supreme
- **Expected Opinions**: https://www.njcourts.gov/attorneys/opinions/expected
- **Published Appellate Court**: https://www.njcourts.gov/attorneys/opinions/published-appellate
- **Unpublished Appellate Court**: https://www.njcourts.gov/attorneys/opinions/unpublished-appellate
- **Published Tax Court**: https://www.njcourts.gov/attorneys/opinions/published-tax
- **Unpublished Tax Court**: https://www.njcourts.gov/attorneys/opinions/unpublished-tax
- **Published Trial Court**: https://www.njcourts.gov/attorneys/opinions/published-trial
- **Unpublished Trial Court**: https://www.njcourts.gov/attorneys/opinions/unpublished-trial
- **Business Opinions**: https://www.njcourts.gov/attorneys/opinions/business
- **Opinion Summaries**: https://www.njcourts.gov/attorneys/opinions/opinion-summaries

### Opinion PDF URLs
- **Pattern**: `/system/files/court-opinions/{YYYY}/{filename}.pdf`
- **Supreme Court Example**: `/system/files/court-opinions/2026/a_45_24.pdf`
- **Appellate Court Example**: `/system/files/court-opinions/2026/a2236-23.pdf`
- **Consolidated Cases**: `/system/files/court-opinions/2026/a3223-23a3239-23.pdf`
- **Redacted Opinions**: `/system/files/court-opinions/2025/a0117-23redacted.pdf`

### Case Briefs URLs
- **Pattern**: `/system/files/cases/briefs/{filename}.pdf`
- **Example**: `/system/files/cases/briefs/a_53_24_petition_for_certification.pdf`

### Individual Case Pages
- **Pattern**: https://www.njcourts.gov/cases/{docket-number}
- **Example**: https://www.njcourts.gov/cases/a-53-24

### Justice Bio Pages
- **Pattern**: https://www.njcourts.gov/public/museum/meet-the-justices/{slug}
- **Example**: https://www.njcourts.gov/public/museum/meet-the-justices/chief-justice-stuart-rabner

### Oral Argument Recordings
- **S3 Storage**: `https://njj-aocmedia-prod-njc-mp4-mp3.s3.amazonaws.com/Misc/Supreme+Court/{filename}.mp4`
- **Library Storage**: `https://library.njcourts.gov/watch/supreme-court/{year}/{filename}.mp4`

---

## Current Justices - New Jersey Supreme Court

| Name | Position | Sworn In | Bio URL |
|------|----------|----------|---------|
| Hon. Stuart Rabner | Chief Justice | June 29, 2007 | https://www.njcourts.gov/public/museum/meet-the-justices/chief-justice-stuart-rabner |
| Hon. Anne M. Patterson | Associate Justice | September 1, 2011 | https://www.njcourts.gov/public/museum/meet-the-justices/associate-justice-anne-m-patterson |
| Hon. Fabiana Pierre-Louis | Associate Justice | September 1, 2020 | https://www.njcourts.gov/public/museum/meet-the-justices/associate-justice-fabiana-pierre-louis |
| Hon. Rachel Wainer Apter | Associate Justice | October 21, 2022 | https://www.njcourts.gov/public/museum/meet-the-justices/associate-justice-rachel-wainer-apter |
| Hon. Douglas M. Fasciale | Associate Justice | October 21, 2022 | https://www.njcourts.gov/public/museum/meet-the-justices/associate-justice-douglas-m-fasciale |
| Hon. Michael Noriega | Associate Justice | July 6, 2023 | https://www.njcourts.gov/public/museum/meet-the-justices/associate-justice-michael-noriega |
| Hon. John Jay Hoffman | Associate Justice | October 2, 2024 | https://www.njcourts.gov/public/museum/meet-the-justices/associate-justice-john-jay-hoffman |

**Notes**:
- Chief Justice Rabner is the 8th Chief Justice since the 1948 state constitution
- Chief Justice Rabner was formerly NJ Attorney General (2006-2007)
- Justice Pierre-Louis is the first Black woman on the NJ Supreme Court
- Justice Wainer Apter clerked for Justice Ruth Bader Ginsburg
- Justice Fasciale previously served in the Appellate Division as presiding judge
- Justices serve initial 7-year term; if reappointed, tenure until age 70

### Recent Retirements
- Justice Barry T. Albin
- Justice Lee A. Solomon
- Justice Jaynee LaVecchia
- Justice Faustino J. Fernandez-Vina

---

## Case Number Formats

### Supreme Court Case Numbers
- **Pattern**: `A-NN-YY` (appeals from Appellate Division)
- **Consolidated**: `A-NN/NN-YY` (e.g., A-74/75/76-24)
- **Special prefix S**: `S-NN-YY` (e.g., S-10-25 for certain matters)
- **Disciplinary matters D**: `D-NNN-YY` (e.g., D-151-24)
- **Motion matters M**: `M-NNNN-YY` (e.g., M-1149-24)

### Appellate Division Case Numbers
- **Pattern**: `A-NNNN-YY`
- **NNNN**: Sequential number
- **YY**: Fiscal year (July-June)
- **Consolidated**: `A-NNNN-YY/A-NNNN-YY`
- **Example**: A-2236-23

### Certification Numbers
- **Pattern**: `NNNNN` (6 digits in parentheses)
- **Example**: (090337) in "A-74/75/76-24 Allstate v. Carteret (090337)"

### Trial Court Docket Numbers
- **Pattern**: `L-NNNN-YY` (Law Division)
- **Pattern**: `FM-NN-NNNN-YY` (Family Division)
- **Pattern**: `FV-NN-NNNN-YY` (Family Violence)
- **Pattern**: `LT-NNNNNN-YY` (Landlord-Tenant)

---

## Opinion Types and Publication

### Opinion Categories
1. **Supreme Court Opinions**: Final appellate decisions
2. **Published Appellate Opinions**: Precedential decisions that can be cited
3. **Unpublished Appellate Opinions**: Non-precedential, cannot be cited
4. **Tax Court Opinions**: Published and unpublished
5. **Trial Court Opinions**: Published and unpublished (Superior Court)
6. **Business Opinions**: Business-related matters

### Publication Schedule
- **Supreme Court**: Posted when issued
- **Appellate Court**: Posted at 10 a.m. each business day
- **Expected Opinions**: Posted at 10 a.m. for following business day

### Document Formats
- **All opinions**: PDF format
- **Oral argument recordings**: MP4 video
- **Briefs**: PDF format

### Volume Statistics (as of January 2026)
- **Supreme Court Opinions**: 783 items (40 pages)
- **Published Appellate Opinions**: 1,123 items (57 pages)

---

## Access Restrictions

### No Login Required
- All opinion pages publicly accessible
- All opinion PDFs publicly accessible
- Justice bio pages publicly accessible
- Oral argument webcasts publicly accessible
- Case briefs publicly accessible

### Login Required
- **eCourts Portal**: https://portal-cloud.njcourts.gov/prweb/PRAuth/CloudSAMLAuth?AppName=ESSO
- eCourts Appellate (attorney filing system)
- JEDS (self-represented litigant electronic filing)

### Rate Limiting
- No obvious rate limiting observed
- Standard web scraping best practices recommended

---

## Oral Arguments

### Supreme Court Webcasts
- **Live streaming**: Available for scheduled arguments
- **Archive**: Recent arguments page at /courts/supreme/supreme-court-webcast/recent-arguments
- **Schedule**: Published at /courts/supreme/arguments
- **Contact for accommodations**: SupremeCtADA.mbx@njcourts.gov
- **Feedback**: Webcast.Mailbox@njcourts.gov

### Appellate Division
- **Livestreaming**: Started September 3, 2024
- **Audio recordings**: Available upon request for remote arguments after Sept 3, 2024
- **Request form**: Request for Audio Records of Appellate Division Oral Arguments
- **Contact**: Appeal-Trans.mailbox@njcourts.gov

### Argument Locations
- Richard J. Hughes Justice Complex, Trenton (Supreme Court)
- Morristown (Appellate Division)
- New Brunswick (Appellate Division)
- Newark (Appellate Division)
- Trenton (Appellate Division)

---

## Technical Implementation Notes

### Website Structure
- **Primary Domain**: njcourts.gov
- **CMS**: Drupal-based
- **Asset Storage**: /system/files/ and /sites/default/files/
- **External Media**: S3 bucket (njj-aocmedia-prod-njc-mp4-mp3.s3.amazonaws.com)
- **Library Storage**: library.njcourts.gov

### Opinions Page Structure
- HTML with JavaScript for filtering/search
- Start/End date filters
- Text search
- Pagination (20 items per page)
- Each entry shows:
  - Case title (link to PDF)
  - Docket number
  - Court type badge
  - Date
  - Summary button (modal)

### Scraping Approach
1. **Opinions**: Parse paginated opinion pages for PDF links
   - Supreme Court: /attorneys/opinions/supreme
   - Published Appellate: /attorneys/opinions/published-appellate
   - Unpublished Appellate: /attorneys/opinions/unpublished-appellate
2. **Oral Arguments**: Parse webcast archive for video links
3. **Briefs**: Available on individual case pages and webcast pages
4. **No RSS Feed**: No obvious RSS/Atom feed for opinions

### Date Handling
- Opinion dates displayed as: Mon. DD, YYYY (e.g., "Jan. 22, 2026")
- PDF paths use: YYYY format for directory (e.g., /2026/)

---

## Example URLs

```
# Supreme Court opinions list
GET https://www.njcourts.gov/attorneys/opinions/supreme

# Supreme Court opinions list page 2
GET https://www.njcourts.gov/attorneys/opinions/supreme?page=1

# Download Supreme Court opinion PDF
GET https://www.njcourts.gov/system/files/court-opinions/2026/a_45_24.pdf

# Published Appellate opinions list
GET https://www.njcourts.gov/attorneys/opinions/published-appellate

# Download Appellate Division opinion PDF
GET https://www.njcourts.gov/system/files/court-opinions/2026/a2236-23.pdf

# Individual case page
GET https://www.njcourts.gov/cases/a-53-24

# Case briefs
GET https://www.njcourts.gov/system/files/cases/briefs/a_53_24_petition_for_certification.pdf

# Supreme Court webcast archive
GET https://www.njcourts.gov/courts/supreme/supreme-court-webcast/recent-arguments

# Justice bio page
GET https://www.njcourts.gov/public/museum/meet-the-justices/chief-justice-stuart-rabner
```

---

## Example Cases

### Recent Supreme Court Opinions (2026)
- **A-45-24, Andris Arias v. County of Bergen (089642)** - Jan. 22, 2026
- **A-42-24, Despina Alice Christakos v. Anthony A. Boyadjis (090214)** - Jan. 20, 2026
- **A-48/49-24, In the Matter of Petition for Rulemaking (089529)** - Jan. 14, 2026
- **A-54/55-24, State v. Michael Owens (089721)** - Jan. 6, 2026

### Recent Appellate Division Opinions (2026)
- **A-2236-23, C.W. vs. Roselle Board of Education** - Jan. 15, 2026 (Record Impounded)
- **A-2328-24, Jean Clau S. Wright vs. NJ State Parole Board** - Jan. 14, 2026
- **A-0891-24, NC Roseville Senior 2016 UR LLC vs. Dorothy Howard** - Jan. 12, 2026
- **A-3643-23, Steven Wronko vs. Monmouth County SPCA** - Jan. 9, 2026

### Recent Oral Arguments (January 2026)
- **A-74/75/76-24**: Allstate New Jersey Insurance Company v. Carteret - Jan. 22, 2026
- **A-53-24**: Alison Beavan v. Allergan U.S.A., Inc. - Jan. 22, 2026
- **A-57-24**: State v. Jesus E. Reyes-Rodriguez - Jan. 21, 2026
- **A-58-24**: State v. Fernando J. Garcia-Moronta - Jan. 21, 2026

---

## Contact Information

### Supreme Court Clerk's Office
- **Clerk**: HeatherJoy Baker
- **Phone**: 609-815-2955
- **Address (mail)**: P.O. Box 970, Trenton, NJ 08625-0970
- **Address (messenger)**: 25 Market Street, Trenton, NJ 08625
- **Building**: Richard J. Hughes Justice Complex

### Appellate Division Clerk's Office
- **Phone**: 609-815-2950 (press 1 for emergent matters)
- **Address**: P.O. Box 006, Trenton, NJ 08625-0970
- **Building**: Richard J. Hughes Justice Complex

### Transcript Unit
- **Phone**: 609-376-3040
- **Email**: Appeal-Trans.mailbox@njcourts.gov

### Social Media
- **YouTube**: https://www.youtube.com/njcourts
- **X/Twitter**: https://twitter.com/njcourts
- **Facebook**: https://www.facebook.com/njcourtsgov/
- **Instagram**: https://www.instagram.com/njcourts/
- **LinkedIn**: https://www.linkedin.com/company/njcourts
- **Threads**: https://www.threads.net/@njcourts

---

## Notes

1. **Unified Court System**: New Jersey has a unified statewide court system, meaning all courts operate under the administrative authority of the Supreme Court and Chief Justice.

2. **1948 Constitution**: The current court structure was established by the 1948 state constitution, which simplified the previously complex court system.

3. **Certification Review**: Most appeals to the Supreme Court are discretionary through petition for certification. The Court grants cert in cases of significant public importance, statutory interpretation issues, or conflicting Appellate Division decisions.

4. **Published vs. Unpublished**: Only "published" opinions set legal precedent and can be cited. Unpublished opinions are not precedential.

5. **Fiscal Year Docketing**: Case numbers use fiscal year (July 1 - June 30), so a case numbered A-1234-23 was filed in fiscal year 2023-24.

6. **Electronic Filing**: eCourts Appellate is mandatory for attorney filings in non-emergent matters.

7. **Livestreaming Expansion**: As of September 2024, the Judiciary livestreams Appellate Division oral arguments in addition to Supreme Court arguments.

8. **Privacy Policy**: https://www.njcourts.gov/privacy

9. **ADA Compliance**: Accommodations and interpreting services available upon request.

10. **Virtual Museum**: The Judiciary maintains a Virtual Museum with historical information about the Supreme Court.
