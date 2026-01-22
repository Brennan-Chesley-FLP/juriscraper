# Maryland Courts Research

## Court Structure

Maryland has a two-tier appellate court system. Both appellate courts were renamed effective December 14, 2022 (November 2022 constitutional amendment).

### 1. Supreme Court of Maryland
- **Website**: https://www.courts.state.md.us/scm
- **Former Name**: Court of Appeals of Maryland (renamed December 14, 2022)
- Highest court in Maryland and court of last resort
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- Justices appointed by the Governor with confirmation by the State Senate
- Handles appeals from the Appellate Court and certain direct appeals
- Published opinions are binding precedent on all Maryland courts

### 2. Appellate Court of Maryland
- **Website**: https://www.courts.state.md.us/acm
- **Former Name**: Court of Special Appeals of Maryland (renamed December 14, 2022)
- Intermediate appellate court
- 15 Judges (1 Chief Judge + 14 Associate Judges)
- Sits in panels of 3 judges
- Hears appeals from Circuit Courts, Orphans' Courts, and certain administrative agencies

### 3. Circuit Courts
- **Website**: https://www.courts.state.md.us/circuit
- Trial courts of general jurisdiction
- 24 Circuit Courts (one per county plus Baltimore City)
- Handles major civil and criminal cases, family law matters

### 4. District Court of Maryland
- **Website**: https://www.courts.state.md.us/district
- Trial court of limited jurisdiction
- Statewide court with 34 locations across 12 districts
- Handles minor civil claims, traffic, misdemeanors, landlord-tenant

---

## Key URLs and URL Patterns

### Maryland Appellate Courts

#### Main Portal
- **Judiciary Home**: https://www.courts.state.md.us/
- **Supreme Court Home**: https://www.courts.state.md.us/scm
- **Appellate Court Home**: https://www.courts.state.md.us/acm
- **Opinions Search**: https://www.courts.state.md.us/opinions/opinions
- **Unreported Opinions**: https://www.courts.state.md.us/appellate/unreportedopinions

#### Opinions Search Interface
- **URL**: https://www.courts.state.md.us/opinions/opinions
- **Features**:
  - Filter by court (Both, Supreme Court of Maryland, Appellate Court of Maryland)
  - Filter by filing year (1995-present)
  - Sort by date, docket number, citation, judge, or party name
  - Search by party name
  - Displays case title, docket number, citation, filing date, judge

#### Published Opinion PDF Patterns
- **Supreme Court (formerly Court of Appeals)**:
  - Domain: `mdcourts.gov` (NOT courts.state.md.us)
  - Pattern: `https://www.mdcourts.gov/data/opinions/coa/{year}/{number}a{yy}.pdf`
  - Examples:
    - `https://www.mdcourts.gov/data/opinions/coa/2025/3a25.pdf` (Docket 3/25)
    - `https://www.mdcourts.gov/data/opinions/coa/2024/1a24.pdf` (Docket 1/24)
  - Filename format: `{case_number}a{2-digit year}.pdf`

- **Appellate Court (formerly Court of Special Appeals)**:
  - Domain: `mdcourts.gov`
  - Pattern: `https://www.mdcourts.gov/data/opinions/cosa/{year}/{number}s{yy}.pdf`
  - Filename format: `{case_number}s{2-digit year}.pdf`

#### Unreported Opinions
- **Archive**: https://www.courts.state.md.us/appellate/unreportedopinions
- **Monthly Listings**: `https://www.courts.state.md.us/appellate/unreportedopinions/list/{YYYYMM}`
  - Example: https://www.courts.state.md.us/appellate/unreportedopinions/list/202501
- Available from May 1, 2015 to present
- Cannot be cited as precedent (only for persuasive value after July 1, 2023)

#### Oral Arguments
- **Webcasts**: https://www.courts.state.md.us/coappeals/webcasts
- Live and archived oral argument recordings available

---

## Current Justices - Supreme Court of Maryland

| Name | Position | Bio URL |
|------|----------|---------|
| Hon. Matthew J. Fader | Chief Justice | https://msa.maryland.gov/msa/mdmanual/31cc/html/msa02871.html |
| Hon. Shirley M. Watts | Associate Justice | https://msa.maryland.gov/msa/mdmanual/31cc/html/msa15313.html |
| Hon. Brynja M. Booth | Associate Justice | https://msa.maryland.gov/msa/mdmanual/31cc/html/msa18015.html |
| Hon. Jonathan Biran | Associate Justice | https://msa.maryland.gov/msa/mdmanual/31cc/html/msa18016.html |
| Hon. Steven B. Gould | Associate Justice | https://msa.maryland.gov/msa/mdmanual/31cc/html/msa18334.html |
| Hon. Angela M. Eaves | Associate Justice | https://msa.maryland.gov/msa/mdmanual/31cc/html/msa18405.html |
| Hon. Peter K. Killough | Associate Justice | https://msa.maryland.gov/msa/mdmanual/31cc/html/msa18677.html |

**Notes**:
- Bio URLs are hosted on Maryland State Archives (msa.maryland.gov)
- Chief Justice Matthew Fader leads both the Supreme Court and the Maryland Judiciary

### Clerk's Office
- **Location**: Robert C. Murphy Courts of Appeal Building, 361 Rowe Boulevard, Annapolis, MD 21401
- **Phone**: (410) 260-1500

---

## Current Judges - Appellate Court of Maryland

The Appellate Court has 15 judges who sit in panels of 3. Full roster available at:
https://www.courts.state.md.us/acm/judges

---

## Opinion Types and Publication

### Published Opinions (Reported)
- **Citation Format**: `{Volume} Md. {Page}` (Supreme Court) or `{Volume} Md. App. {Page}` (Appellate Court)
- Official published opinions with binding precedential value
- Available through opinions search from 1995-present

### Unreported Opinions
- **URL**: https://www.courts.state.md.us/appellate/unreportedopinions
- Available online from May 1, 2015 to present
- **Citation Rules** (Maryland Rule 1-104):
  - Before July 1, 2018: Cannot be cited
  - July 1, 2018 - June 30, 2023: May be cited only if no published opinion addresses the issue
  - After July 1, 2023: May be cited for persuasive value only (not binding precedent)
- Organized by month in archive listings

### Docket Number Format
- **Pattern**: `{case_number}/{term_year}`
- **Examples**:
  - `3/25` (Case 3 of 2025 term)
  - `1991/23` (Case 1991 of 2023 term)
  - `47/24` (Case 47 of 2024 term)

---

## Access Restrictions

### No Login Required
- All court websites are publicly accessible
- Published opinions freely downloadable as PDFs
- Unreported opinions available online (May 2015 - present)
- Justice/Judge biographies on Maryland State Archives

### Case Search
- **Maryland Case Search**: https://casesearch.courts.state.md.us/casesearch/
- Public access to case information
- Some restrictions on sealed/expunged records

### eFiling
- **MDEC (Maryland Electronic Courts)**: https://mdcourts.gov/mdec
- Electronic filing system for Maryland courts
- Statewide implementation complete

### Notes
- No reCAPTCHA or anti-bot measures observed on opinion pages
- PDFs are direct links on mdcourts.gov domain
- Two different domains used: courts.state.md.us (main site) and mdcourts.gov (PDFs/MDEC)

---

## Technical Implementation Notes

### Website Structure
- **Main Domain**: courts.state.md.us
- **PDF Domain**: mdcourts.gov
- Opinions search provides filterable, sortable interface
- PDFs organized by year in `/data/opinions/{court}/{year}/` directory
- Court codes: `coa` = Supreme Court (Court of Appeals), `cosa` = Appellate Court (Court of Special Appeals)

### Opinion PDF Files
- Supreme Court: `{case_number}a{yy}.pdf` (a = appeals)
- Appellate Court: `{case_number}s{yy}.pdf` (s = special appeals)
- Direct downloadable links via mdcourts.gov

### Data Available for Each Published Opinion
- Case title/parties
- Docket number (case/year format)
- Citation (Md. or Md. App.)
- Filing date
- Authoring judge/justice
- Direct PDF URL

### Data Available for Each Unreported Opinion
- Case title/parties
- Filing date
- Authoring judge
- Monthly archive organization

---

## Example Cases

### Supreme Court of Maryland (2025)
- **Docket 3/25**: Most recent Supreme Court opinion as of research date
- Available at: https://www.mdcourts.gov/data/opinions/coa/2025/3a25.pdf

### Unreported Opinions Archive
- January 2025: https://www.courts.state.md.us/appellate/unreportedopinions/list/202501
- December 2024: https://www.courts.state.md.us/appellate/unreportedopinions/list/202412

---

## Recommended Scraper Architecture

### 1. Maryland Supreme Court Opinion Scraper
**Source**: https://www.courts.state.md.us/opinions/opinions (filter: Supreme Court of Maryland)

**Approach**:
1. Navigate to opinions search page
2. Filter by court = "Supreme Court of Maryland"
3. Filter by year as needed
4. Parse search results table
5. Extract:
   - Case title from party names column
   - Docket number (case/year format)
   - Citation (Md. reporter)
   - Filing date
   - Authoring justice
6. Construct PDF URL using mdcourts.gov pattern

**Data Available**:
- Full case metadata from search results
- PDF URL constructible from docket number

### 2. Maryland Appellate Court Opinion Scraper
**Source**: https://www.courts.state.md.us/opinions/opinions (filter: Appellate Court of Maryland)

**Approach**:
1. Same as Supreme Court scraper but filter for Appellate Court
2. Use `cosa` path and `s` suffix for PDF URLs

### 3. Unreported Opinions Scraper
**Source**: https://www.courts.state.md.us/appellate/unreportedopinions

**Approach**:
1. Navigate to unreported opinions archive
2. Iterate through monthly listings (YYYYMM format)
3. Parse opinion listings
4. Extract case metadata and PDF links
5. Note: Available from May 2015 onward

---

## Additional Resources

### Court Rules
- **Maryland Rules**: https://www.courts.state.md.us/rules
- **Rule 1-104**: Governs citation of unreported opinions

### Contact Information
- **Administrative Office of the Courts**:
  - 2001-D Commerce Park Drive, Annapolis, MD 21401
  - Phone: (410) 260-1400
- **Clerk of the Supreme Court**: (410) 260-1500
- **Clerk of the Appellate Court**: (410) 260-1450

### Related Links
- **Maryland State Archives**: https://msa.maryland.gov/ (judicial biographies)
- **MDEC**: https://mdcourts.gov/mdec (electronic filing)
- **Case Search**: https://casesearch.courts.state.md.us/casesearch/
- **Court Schedules**: https://www.courts.state.md.us/calendars

---

## Notes

1. **Court Renaming (2022)**: The Court of Appeals became the Supreme Court of Maryland, and the Court of Special Appeals became the Appellate Court of Maryland, effective December 14, 2022. Old court names may still appear in older opinions and documents.

2. **Two Domains**: Maryland uses `courts.state.md.us` for the main website and `mdcourts.gov` for PDFs and the MDEC system. Both domains are official.

3. **PDF URL Codes**:
   - `coa` = Court of Appeals (now Supreme Court)
   - `cosa` = Court of Special Appeals (now Appellate Court)
   - Filename suffix `a` = appeals, `s` = special appeals

4. **Unreported Opinion Citation**: Maryland has a tiered system for citing unreported opinions based on the opinion date. Check Rule 1-104 for current requirements.

5. **Opinion Availability**: Published opinions available from 1995-present through the search interface. Unreported opinions available from May 2015-present.

6. **Appellate Court Panels**: The Appellate Court sits in panels of 3 judges, unlike the Supreme Court where all 7 justices typically hear cases.
