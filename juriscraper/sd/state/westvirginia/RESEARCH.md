# West Virginia Appellate Courts Research

## Court Structure

West Virginia has two appellate courts:

### 1. Supreme Court of Appeals of West Virginia (SCA)
- **Role**: West Virginia's highest court with judicial and administrative jurisdiction over the entire state court system
- **Composition**: 5 Justices elected to 12-year terms in nonpartisan statewide elections
- **Location**: Charleston, but may hold hearings in other cities
- **Terms**: Two terms per year:
  - Spring Term: Second Tuesday in January through June
  - Fall Term: First Wednesday in September through November
- **Jurisdiction**:
  - Appeals from ICA decisions
  - Appeals from circuit court in criminal matters, juvenile proceedings, child abuse/neglect proceedings
  - Extraordinary writs (habeas corpus, mandamus, quo warranto, prohibition, certiorari)
  - Cases requiring interpretation of WV and US laws/constitutions
- **Note**: West Virginia does not have the death penalty

### 2. Intermediate Court of Appeals of West Virginia (ICA)
- **Opened**: July 1, 2022 (relatively new court)
- **Composition**: 3 Judges elected to 10-year terms in nonpartisan elections
- **Location**: Primary in Charleston, with 5 satellite courtroom locations for virtual oral arguments
- **Jurisdiction**:
  - Civil appeals
  - Family appeals (including 50/50 custody interlocutory appeals)
  - Worker's Compensation Board of Review appeals
  - Administrative appeals
  - Guardianship/Conservatorship appeals
- **Precedent**: All ICA opinions are binding on circuit courts, family courts, magistrate courts, and state administrative agencies unless overruled by SCA

## Current Justices - Supreme Court of Appeals

| Position | Name | Bio URL | Appointed/Elected |
|----------|------|---------|-------------------|
| Chief Justice | C. Haley Bunn | https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/justices-staff/justice-bunn | Appointed April 6, 2022; Elected to 12-year term starting Jan 1, 2025 |
| Justice | Charles S. Trump, IV | https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/justices-staff/justice-trump | - |
| Justice | Thomas H. Ewing | https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/justices-staff/justice-ewing | - |
| Justice | Gerald M. Titus, III | https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/justices-staff/justice-titus | - |
| Justice | William R. Wooton | https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/justices-staff/justice-wooton | - |

## Current Judges - Intermediate Court of Appeals

| Position | Name | Bio URL | Notes |
|----------|------|---------|-------|
| Chief Judge | Daniel W. Greear | https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/judges-staff/greear | Appointed 2021 |
| Judge | Charles O. Lorensen | https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/judges-staff/lorensen | Original appointee |
| Judge | Ryan White | https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/judges-staff/judge-white | Elected 2024, 10-year term starting Jan 1, 2025 (replaced Judge Thomas E. Scarr) |

## URL Patterns

### Base URL
- `https://www.courtswv.gov`

### Opinions

#### SCA Current Term Opinions
- **Page**: `https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/opinions`
- **PDF Pattern**: `/sites/default/pubfilesmnt/{YYYY-MM}/{case_no}%20{decision_type}.pdf`
- **Example**: `/sites/default/pubfilesmnt/2026-01/25-576%20md.pdf`

#### SCA Prior Term/Year Search
- **Page**: `https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/opinions/prior-terms`
- **Total Opinions**: 17,673 (as of January 2026)
- **Date Range**: 1991 to present
- **Filters**: Year, Term (January/Spring or September/Fall), Case Type, Decision Type, Search text

#### ICA Current Term Opinions
- **Page**: `https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/opinions`
- **PDF Pattern**: `/sites/default/pubfilesmnt/{YYYY-MM}/{case_no}_{decision_type}.pdf`
- **Example**: `/sites/default/pubfilesmnt/2026-01/25-ICA-304_MD.pdf`
- **Note**: ICA case numbers include "ICA" prefix (e.g., `25-ICA-304`)

#### ICA Prior Term/Year Search
- **Page**: `https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/opinions/prior-terms`
- **Total Opinions**: 1,185 (as of January 2026)
- **Date Range**: 2022 to present (court opened July 1, 2022)
- **Filters**: Term, Year, Case Type, Decision Type, Search text

### Decision Types

| Code | Name | Description |
|------|------|-------------|
| SO | Signed Opinion | Contains at least one new syllabus point; published in WV Reports |
| PC | Per Curiam Opinion | Delivered by Court as a whole; no new syllabus points (no longer used per State v. McKinley, 2014) |
| MD | Memorandum Decision | Abbreviated decision; not published in WV Reports; citable |
| SEP | Separate Opinion | Concurring or dissenting opinion by individual justice |
| Order | Order | Various court orders |

### Case Type Codes

| Code | Type | Description |
|------|------|-------------|
| CR-F | Felony (non-Death Penalty) | Criminal felony appeals |
| CR-M | Misdemeanor | Criminal misdemeanor appeals |
| CR-O | Criminal-Other | Sex offender registration, expungement |
| TCR | Tort, Contract, Real Property | Civil disputes |
| PR | Probate | Guardianships, estates, wills |
| FAM | Family | Divorce, custody, adoption, protection orders |
| JUV | Juvenile | Abuse/neglect proceedings under Chapter 49 |
| CIV-O | Civil-Other | Civil forfeiture, other civil |
| POST | Post-Conviction | Habeas corpus, post-conviction relief |
| WC | Worker's Compensation | Work injury compensation disputes |
| TAX | Revenue (Tax) | Tax law disputes |
| ADM | Administrative Agency-Other | PSC, Human Rights Commission appeals |
| OJ-H | Habeas Corpus | Original habeas corpus applications |
| OJ-M | Mandamus | Writ of mandamus |
| OJ-P | Prohibition | Writ of prohibition |
| L-ADM | Bar Admission | Bar admission disputes |
| L-DISC | Bar Discipline | Attorney discipline matters |
| J-DISC | Judicial Discipline | Judge discipline matters |
| CERQ | Certified Question | Questions certified from other courts |
| MISC | Other | Appeals not fitting other categories |

### Dockets

#### SCA Docket
- **Page**: `https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/current-docket`
- **Monthly Pages**: `/appellate-courts/supreme-court-of-appeals/current-docket/{month}` (january, february, etc.)
- **Case Detail**: `/node/{node_id}` (e.g., `/node/34921`)
- **Calendar PDF**: `/sites/default/pubfilesmnt/{YYYY-MM}/{YYYY}%20SCA%20Calendar%20-%20Final_0.pdf`
- **Filters**: Docket Year, Argument Type, Search text
- **Argument Types**: RULE 19 ARGUMENT, RULE 20 ARGUMENT, ORDER LIST, ADMISSIONS, BAKER'S CUP

#### SCA Case Detail Page Contains:
- Docket date and time
- Case name and number
- Argument type
- Links to briefs (PDFs)
- Notes (e.g., justice disqualifications)

#### ICA Docket
- **Page**: `https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/current-docket`

### Order Lists

#### SCA Order Lists
- **Page**: `https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/order-lists`
- **PDF Pattern**: `/sites/default/pubfilesmnt/{YYYY-MM}/OrderList{MonthDayYear}.pdf`
- **Example**: `/sites/default/pubfilesmnt/2025-06/OrderListJune262025.pdf`

#### ICA Order Lists
- **Page**: `https://www.courtswv.gov/appellate-courts/intermediate-court-of-appeals/order-lists`

### Briefs
- **Pattern**: `/sites/default/pubfilesmnt/{YYYY-MM}/{case_no}%20{brief_type}.pdf`
- **Brief Types**: `Petitioner Brief`, `Respondent Brief`, `Reply Brief`, `Order Certifying Question`
- **Example**: `/sites/default/pubfilesmnt/2026-01/24-661%20Petitioner%20Brief.pdf`

## Oral Arguments

- **Webcast Page**: `https://www.courtswv.gov/appellate-courts/argument-webcast`
- **YouTube Channel**: `https://www.youtube.com/c/wvsupremecourt`
- **Call-in Line**: 304-558-1313 (Charleston hearings only)
- **Schedule**: Arguments commence at 10:00 AM on argument days; check court calendar
- **Archive**: Oral argument recordings are NOT archived - live webcast only
- **Available Since**: September 2001 term
- **Simulcast**: May be simulcast on WV Public Broadcasting's The West Virginia Channel

## Opinion Information
- **Page**: `https://www.courtswv.gov/appellate-courts/supreme-court-of-appeals/opinions/opinion-information`
- **Slip Opinions Release**: Weekdays at 3:00 PM (separate opinions may be released anytime after majority opinion)
- **Note**: Slip opinions are not final; subject to modification and petitions for rehearing per Rule 25
- **Copies**: Hard copies available from Clerk's Office at $1/page for opinions, .25/page for pending cases, $1/page for closed cases

## Technical Implementation Notes

### Data Format
- Opinions are HTML tables with JavaScript-based filtering/search
- Tables have columns: Date Filed, Case No, Case Name, Case Type, Decision Type
- PDFs are stored in year-month directories under `/sites/default/pubfilesmnt/`
- Pagination uses `?page=N` query parameter (0-indexed)

### Search/Filter Interface
- Client-side filtering via dropdowns (Case Type, Decision Type)
- Text search box for case-related information
- No apparent API - data is rendered in HTML tables

### URL Encoding
- Spaces in filenames are URL-encoded as `%20`
- Case numbers may contain hyphens

### Access Restrictions
- No login required for opinions, dockets, or order lists
- All content is publicly accessible
- No rate limiting observed
- Slip opinions are released at 3:00 PM weekdays
- Oral arguments are live-streamed only, not archived

## Example Cases

### SCA Example
- **Case**: Frank Mayer v. City of Clarksburg
- **Case No**: 25-765
- **Date Filed**: 01/21/2026
- **Case Type**: WC (Worker's Compensation)
- **Decision Type**: MD (Memorandum Decision)
- **PDF URL**: `https://www.courtswv.gov/sites/default/pubfilesmnt/2026-01/25-576%20md.pdf`

### ICA Example
- **Case**: Amy Hull-Wright et al. v. Arsenal Resources, LLC
- **Case No**: 25-ICA-304
- **Date Filed**: 01/16/2026
- **Case Type**: ADM (Administrative)
- **Decision Type**: MD (Memorandum Decision)
- **PDF URL**: `https://www.courtswv.gov/sites/default/pubfilesmnt/2026-01/25-ICA-304_MD.pdf`

## Related Links

- **Main Website**: https://www.courtswv.gov
- **Court Rules**: https://www.courtswv.gov/legal-community/court-rules
- **E-Filing**: https://www.courtswv.gov/legal-community/e-filing
- **Court Record Access**: https://www.courtswv.gov/court-record-access
- **Contact**: https://www.courtswv.gov/supreme-court-contacts

## Implementation Recommendations

1. **Start with SCA opinions** - larger corpus (17,673 opinions from 1991)
2. **Use prior term search page** for bulk scraping
3. **PDF extraction** will be needed for opinion content
4. **ICA is newer** - smaller corpus (1,185 opinions from 2022)
5. **Case number patterns**:
   - SCA: `{YY}-{number}` (e.g., `25-765`)
   - ICA: `{YY}-ICA-{number}` (e.g., `25-ICA-304`)
6. **PDF naming conventions differ** between SCA and ICA (space vs underscore separator)
