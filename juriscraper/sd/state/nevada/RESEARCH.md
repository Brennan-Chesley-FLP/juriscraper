# Nevada Courts Research

## Court Structure

Nevada has a two-tier appellate court system with a Supreme Court and an intermediate Court of Appeals.

### 1. Nevada Supreme Court
- **Website**: https://nvcourts.gov/supreme
- Highest court in Nevada
- 7 Justices (includes 1 Chief Justice)
- Justices elected in nonpartisan elections for 6-year terms
- Two locations: Carson City (main) and Las Vegas
  - Carson City: 201 South Carson Street, Suite 201, Carson City, NV 89701-4702, (775) 684-1600
  - Las Vegas: 408 East Clark Avenue, Las Vegas, NV 89101, (702) 486-9300
- Chief Justice: Douglas Herndon (named January 2025)

#### Jurisdiction
- Original jurisdiction in certain matters
- Appellate jurisdiction over Court of Appeals decisions (by discretionary review)
- Direct appeals in death penalty cases and certain other matters
- Deflective model: assigns approximately 1/3 of cases to Court of Appeals

### 2. Nevada Court of Appeals
- **Website**: https://nvcourts.gov/supreme/court_information/court_of_appeals
- Intermediate appellate court created in 2014 (voter-approved constitutional amendment)
- 3 Judges
- Chief Judge: Bonnie A. Bulla (appointed January 2025)
- Uses deflective model - Supreme Court assigns cases to Court of Appeals
- Handles approximately 700 cases per year

#### Jurisdiction
- Cases assigned by the Supreme Court
- Non-precedent-setting matters
- Most family law, criminal, and civil appeals
- Decisions may be reviewed by Supreme Court in extraordinary cases

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://nvcourts.gov/
- **Appellate Courts Home**: https://nvcourts.gov/supreme
- **Calendar**: https://nvcourts.gov/calendar
- **Site Map**: https://nvcourts.gov/supreme/sitemap

### Decisions and Opinions
- **Advance Opinions**: https://nvcourts.gov/supreme/decisions/advance_opinions
  - Published opinions with search by Advance No., Case Title, or Date
  - Searchable table interface
- **Forthcoming Opinions**: https://nvcourts.gov/supreme/decisions/forthcoming_opinions
- **Nevada Reports**: https://nvcourts.gov/supreme/decisions/nevada_reports
  - Preliminary prints of bound volume pages
  - Batched PDF downloads (4-6 opinions per batch)
  - URL Pattern: `https://nvcourts.gov/__data/assets/pdf_file/{ID1}/{ID2}/{VOL}_nevada_reports_pages_{START}-{END}.pdf`
  - Current volumes: 130-140
- **Unpublished Orders**: https://nvcourts.gov/supreme/decisions/unpublished_orders
- **Administrative Orders**: https://nvcourts.gov/supreme/decisions/administrative_orders

### Case Lookup
- **Case Lookup (on main page)**: https://nvcourts.gov/supreme
  - Search by Case Number or Caption Contains
  - Form-based search on the appellate courts homepage
- Case information pages accessible via search results

### Oral Arguments
- **Upcoming Synopses**: https://nvcourts.gov/supreme/arguments/upcoming_oral_argument_synopses
- **Prior Synopses**: https://nvcourts.gov/supreme/arguments/prior_oral_argument_synopses
- **Prior Recordings**: https://nvcourts.gov/supreme/arguments/prior_oral_argument_recordings
  - Paginated list with pagination parameter: `?result_36838_result_page={N}`
- **Public Hearing Recordings**: https://nvcourts.gov/supreme/arguments/public_hearing_recordings
- **Individual Recording Page Pattern**: `https://nvcourts.gov/supreme/arguments/recordings/{CASE_SLUG}`
  - Example: `https://nvcourts.gov/supreme/arguments/recordings/89445_silvanus_damien_vs._state_criminal_01072026`

### Audio Files
- **Audio Download Pattern**: `https://nvcourts.gov/__data/assets/audio_file/{ID1}/{ID2}/{DATE}_{CASE_NO}.mp3`
  - Example: `https://nvcourts.gov/__data/assets/audio_file/0024/49362/010726_89445.mp3`
  - Date format: MMDDYY
  - Audio format: MP3

### Judge/Justice Bio Pages
- **Justices Index**: https://nvcourts.gov/supreme/court_information/justices
- **Justice Bio Pattern**: `https://nvcourts.gov/supreme/court_information/justices/{lastname},_{firstname}`
  - Example: `https://nvcourts.gov/supreme/court_information/justices/herndon,_douglas`
- **Court of Appeals Judges**: https://nvcourts.gov/supreme/court_information/court_of_appeals/judges/{judge_slug}`
  - Example: `https://nvcourts.gov/supreme/court_information/court_of_appeals/judges/judge_bonnie_a_bulla`

### RSS Feeds
- **Main RSS Feed**: https://nvcourts.gov/supreme/rss
  - Redirects to: `https://nvcourts.gov/supreme/all_news?SQ_DESIGN_NAME=xml&SQ_PAINT_LAYOUT_NAME=rss&root=36127`
  - RSS 2.0 format
  - Covers news items from Appellate Courts

---

## Current Justices - Nevada Supreme Court

| Name | Position | Seat | Bio URL |
|------|----------|------|---------|
| Hon. Douglas Herndon | Chief Justice | Seat D | https://nvcourts.gov/supreme/court_information/justices/herndon,_douglas |
| Hon. Lidia S. Stiglich | Justice | - | https://nvcourts.gov/supreme/court_information/justices/stiglich,_lidia_s_ |
| Hon. Elissa F. Cadish | Justice | - | https://nvcourts.gov/supreme/court_information/justices/cadish,_elissa_f_ |
| Hon. Kristina Pickering | Justice | - | https://nvcourts.gov/supreme/court_information/justices/pickering,_kristina |
| Hon. Ron D. Parraguirre | Justice | - | https://nvcourts.gov/supreme/court_information/justices/parraguirre,_ron_d_ |
| Hon. Linda Marie Bell | Justice | - | https://nvcourts.gov/supreme/court_information/justices/justice_linda_marie_bell |
| Hon. Patricia Lee | Justice | - | https://nvcourts.gov/supreme/court_information/justices/justice_patricia_lee |

**Notes**:
- Chief Justice Herndon was named Chief Justice in January 2025
- Herndon elected to Supreme Court in November 2020
- Previously served as District Court Judge for 15 years
- All justices elected in nonpartisan elections for 6-year terms

---

## Current Judges - Nevada Court of Appeals

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Bonnie A. Bulla | Chief Judge | https://nvcourts.gov/supreme/court_information/court_of_appeals/judges/judge_bonnie_a_bulla |
| Hon. Michael P. Gibbons | Judge | https://nvcourts.gov/supreme/court_information/court_of_appeals/judges/judge_michael_p_gibbons |
| Hon. Deborah L. Westbrook | Judge | https://nvcourts.gov/supreme/court_information/court_of_appeals/judges/judge_deborah_l._westbrook |

**Notes**:
- Chief Judge Bulla appointed as Chief Judge in January 2025
- Court of Appeals created in 2014 by voter-approved constitutional amendment

---

## Case Number Format

Nevada appellate case numbers are 5-digit numbers.

### Examples
- `89445` - Silvanus (Damien) vs. State (Criminal)
- `90366` - Davis vs. Dist. Ct. (Ohanian) (Civil)
- `88946` - Lennar Comm. Nev., LLC vs. Whalen (Civil)
- `87000` - Example case number format

### Case Types (from case titles)
- Criminal
- Civil
- Family (including Child Custody)
- Administrative appeals

---

## Opinion Types and Publication

### Advance Opinions
- Published opinions from both Supreme Court and Court of Appeals
- Searchable by Advance No., Case Title, or Date
- Available on Advance Opinions page

### Nevada Reports
- Official bound volumes of published opinions
- Preliminary prints posted as PDF batches
- Batches contain 4-6 opinions each
- Current volumes: 130-140
- Contact Clerk for typographical corrections before final publication

### Unpublished Orders
- Apply only to parties involved in the appeal
- Not precedent-setting
- Searchable and downloadable

### Document Formats
- Opinions: PDF format
- Nevada Reports batches: PDF format
- Oral argument recordings: MP3 audio

---

## Access Restrictions

### No Login Required
- All opinion pages publicly accessible
- Case lookup publicly accessible
- Justice/Judge bio pages publicly accessible
- Oral argument recordings publicly accessible
- RSS feeds publicly accessible

### Rate Limiting
- No obvious rate limiting observed
- Standard web scraping best practices recommended
- Contact IT Service Desk for access issues: itservicedesk@nvcourts.nv.gov

---

## Oral Arguments

### Schedule
- **Upcoming Arguments**: Listed on Upcoming Oral Argument Synopses page
- Arguments held at both Carson City and Las Vegas locations
- En Banc sessions and Panel sessions

### Recordings
- **Audio Format**: MP3
- **Download Available**: Direct download links on recording pages
- **Recording Info**: Includes docket number, date, time, location, panel info, appearances, and timestamps
- **Timestamp Format**: Linked timestamps in recording tables

### Panel Information
- Panel designations: En Banc, Panel B25, Panel B26, etc.
- Justice assignments noted on individual case pages

---

## Technical Implementation Notes

### Website Structure
- **Primary Domain**: nvcourts.gov
- **Appellate Courts Section**: nvcourts.gov/supreme
- **Asset Storage**: nvcourts.gov/__data/assets/
  - PDF files: `/pdf_file/`
  - Audio files: `/audio_file/`
- Built on Matrix CMS (indicated by URL patterns)

### Advance Opinions Page
- HTML table structure with search functionality
- Columns: Case Title (linked), Date
- Client-side JavaScript search with dropdown for field selection
- Lists recent advance opinions

### Unpublished Orders Page
- Similar table structure to Advance Opinions
- Very large page with many entries
- Searchable interface

### RSS Feed
- RSS 2.0 format
- Contains news items (not opinions)
- URL: https://nvcourts.gov/supreme/rss

### Scraping Approach
1. **Advance Opinions**: Parse Advance Opinions page for new published opinions
2. **Unpublished Orders**: Parse Unpublished Orders page for new orders
3. **Oral Arguments**: Parse Prior Recordings page for audio files
4. **Nevada Reports**: Parse Nevada Reports page for batch PDF downloads

### Date Handling
- Filing dates displayed as: MM/DD/YYYY
- Oral argument recording dates in titles: MM/DD/YYYY format
- Audio file names use: MMDDYY format

### Example URLs
```
# Advance Opinions list
GET https://nvcourts.gov/supreme/decisions/advance_opinions

# Unpublished Orders list
GET https://nvcourts.gov/supreme/decisions/unpublished_orders

# Nevada Reports batches
GET https://nvcourts.gov/supreme/decisions/nevada_reports

# Prior Oral Argument Recordings (paginated)
GET https://nvcourts.gov/supreme/arguments/prior_oral_argument_recordings?result_36838_result_page=1

# Individual recording page
GET https://nvcourts.gov/supreme/arguments/recordings/89445_silvanus_damien_vs._state_criminal_01072026

# Download audio file
GET https://nvcourts.gov/__data/assets/audio_file/0024/49362/010726_89445.mp3

# Download Nevada Reports batch PDF
GET https://nvcourts.gov/__data/assets/pdf_file/0028/48493/140_Nevada_Reports_pages_1-61.pdf
```

---

## Example Cases

### Recent Advance Opinions (January 2026)
- **AJAY (AJAY) VS. STATE (CRIMINAL)** - 01/15/2026
- **ROGERS VS. STATE OF NEVADA** - 01/15/2026
- **IN RE: N.D., G.D. AND M.D. (FAMILY)** - 01/08/2026
- **DEUTSCHE BANK NAT'L TR. CO. VS. COLLEGIUM FUND LLC SER. 16** - 01/08/2026

### Recent Oral Arguments (December 2025 - January 2026)
- **89445 Silvanus (Damien) vs. State (Criminal)** - 01/07/2026, Panel B25
- **90366 Davis vs. Dist. Ct. (Ohanian) (Civil)** - 01/07/2026
- **88946 Lennar Comm. Nev., LLC vs. Whalen (Civil)** - 12/10/2025
- **88680 Civil Liberties Union of Nev. vs. Clark Cnty. School Dist.** - 12/09/2025

---

## Contact Information

### Clerk of the Supreme Court
- **Carson City**: (775) 684-1600
- **Las Vegas**: (702) 486-9300
- **Email for Advance Sheets corrections**: nvscclerk@nvcourts.nv.gov
- **General Contact**: https://nvcourts.gov/supreme/court_information/contact_us

### IT Support
- **Email**: itservicedesk@nvcourts.nv.gov

### Social Media
- **Facebook**: https://facebook.com/nevadaappellatecourts
- **LinkedIn**: https://www.linkedin.com/company/nevada-supreme-court

---

## Notes

1. **Deflective Model**: Nevada uses a unique deflective model where the Supreme Court receives all appeals and then assigns approximately 1/3 of cases to the Court of Appeals. This is similar to Iowa, Idaho, and Mississippi.

2. **Court of Appeals Created 2014**: The Court of Appeals was created by voter-approved constitutional amendment in November 2014 to reduce the Supreme Court's backlog.

3. **Two Locations**: Both the Supreme Court and Court of Appeals maintain offices in Carson City and Las Vegas.

4. **Nevada Reports**: The official bound volumes of Nevada Reports are published by the Legislative Counsel Bureau: https://shop.leg.state.nv.us/

5. **Oral Argument Recordings**: Available as MP3 downloads with detailed timestamp information for each speaker.

6. **Court Rules**: Available at https://www.leg.state.nv.us/Division/Legal/LawLibrary/CourtRules/

7. **Fee Policy**: Information at https://nvcourts.gov/supreme/court_information/fee_policy

8. **Privacy Policy**: https://nvcourts.gov/supreme/use_and_privacy_policy

9. **ADA Assistance**: http://adahelp.nv.gov
