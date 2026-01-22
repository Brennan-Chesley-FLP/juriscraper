# Indiana Courts Research

## Court Structure

Indiana has a three-tier appellate court system: the Indiana Supreme Court at the apex, the Court of Appeals of Indiana as the intermediate appellate court, and a specialized Tax Court.

### 1. Indiana Supreme Court
- **Website**: https://www.in.gov/courts/supreme/
- Highest court in Indiana
- 5 Justices (1 Chief Justice + 4 Associate Justices)
- Justices are nominated by the Judicial Nominating Commission, appointed by the Governor, then face nonpartisan retention elections
- 10-year terms after initial retention vote
- Location: 315 Indiana State House, 200 W. Washington Street, Indianapolis, IN 46204
- Phone: 317-232-2540

### 2. Court of Appeals of Indiana
- **Website**: https://www.in.gov/courts/appeals/
- Intermediate appellate court
- 15 Judges divided into 5 districts (3 judges per district)
- Created in 1891
- Chief Judge chosen by members of the Court for 3-year term
- Hears most appeals from trial courts
- Decisions may be appealed to the Supreme Court

### 3. Indiana Tax Court
- **Website**: https://www.in.gov/courts/tax/
- Specialized court established July 1, 1986
- 1 Judge appointed by the Governor from Judicial Nominating Commission nominees
- 10-year terms after initial retention vote
- Exclusive jurisdiction over Indiana tax law cases
- Location: 115 W. Washington Street, Suite 960S, Indianapolis, IN 46204
- Phone: 317-232-4694

---

## Key URLs and URL Patterns

### Main Portal
- **Courts Home**: https://www.in.gov/courts/
- **Appellate Decisions Portal**: https://public.courts.in.gov/decisions
- **Supreme Court Opinions**: https://public.courts.in.gov/decisions?c=9510
- **Court of Appeals Opinions**: https://public.courts.in.gov/decisions?c=9530
- **Tax Court Opinions**: https://public.courts.in.gov/decisions?c=9550

### Case Search
- **myCase Portal**: https://mycase.in.gov/
- **Public Courts Portal**: https://public.courts.in.gov/
- **Case Summary View**: https://public.courts.in.gov/mycase/#/vw/CaseSummary/{base64-encoded-token}

### Oral Arguments
- **Oral Arguments Portal**: https://mycourts.in.gov/arguments/
- **Events Calendar**: https://events.in.gov/courts
- Archives available from 2001 to present
- Live webcasts and archived videos available

### Court Rules
- **All Rules**: https://rules.incourts.gov/Content/index.htm
- **Appellate Rules**: https://rules.incourts.gov/Content/appellate/default.htm
- **Trial Rules**: https://rules.incourts.gov/Content/trial/default.htm
- **Tax Court Rules**: https://www.in.gov/courts/rules/tax/index.html

### Court Information
- **Supreme Court Justices**: https://www.in.gov/courts/supreme/justices/
- **Court of Appeals Judges**: https://www.in.gov/courts/appeals/judges/
- **Tax Court Judge**: https://www.in.gov/courts/tax/justin-mcadam/
- **Historical Judge Listing**: https://mycourts.in.gov/JR/Default.aspx
- **Transfer Dispositions**: https://www.in.gov/courts/clerk/transfer
- **Orders**: https://www.in.gov/courts/public-records/orders

---

## Opinion Search API

### Decisions Portal API
The opinions are served via an AngularJS application with API endpoints:

**Base URL**: `https://public.courts.in.gov/decisions`

**Search Parameters** (as JSON in API request):
- `caseParty`: Case number or party name
- `courtId`: Court filter (empty for all, specific ID for single court)
- `caseCategoryId`: Case category (Criminal, Civil, Juvenile, etc.)
- `judgeId`: Authoring judge filter
- `fromDate`: Start date filter
- `toDate`: End date filter
- `countyId`: County filter
- `showMemorandum`: Include memorandum decisions (boolean)

**Court IDs**:
- `9510`: Supreme Court
- `9530`: Court of Appeals
- `9550`: Tax Court

### Opinion PDF URLs
- **Pattern**: `https://public.courts.in.gov/decisions/api/Document/Opinion?Id={opinion-id}`
- Opinion IDs are base64-like encoded strings
- Example: `api/Document/Opinion?Id=14qhbbHnhfrM_A7WeRi1bLIgbGGYrPCWY5YRPMpRBAcs-HMgaJe9r8SDHW4QBtWY0`

### Case Detail URLs
- **Pattern**: `https://public.courts.in.gov/mycase/#/vw/CaseSummary/{base64-token}`
- Token contains case information encoded in base64

---

## Current Justices - Indiana Supreme Court

| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Loretta H. Rush | Chief Justice (108th) | November 7, 2012 | https://www.in.gov/courts/supreme/justices/loretta-rush |
| Mark S. Massa | Associate Justice (107th) | April 2, 2012 | https://www.in.gov/courts/supreme/justices/mark-massa |
| Geoffrey G. Slaughter | Associate Justice (109th) | June 13, 2016 | https://www.in.gov/courts/supreme/justices/geoffrey-slaughter |
| Christopher M. Goff | Associate Justice (110th) | July 24, 2017 | https://www.in.gov/courts/supreme/justices/christopher-goff |
| Derek R. Molter | Associate Justice (111th) | September 1, 2022 | https://www.in.gov/courts/supreme/justices/derek-molter |

---

## Current Judges - Court of Appeals of Indiana

### First District
| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| L. Mark Bailey | Presiding Judge | January 30, 1998 | https://www.in.gov/courts/appeals/judges/mark-bailey |
| Leanna K. Weissmann | Judge | September 14, 2020 | https://www.in.gov/courts/appeals/judges/leanna-weissmann |
| Peter R. Foley | Judge | October 11, 2022 | https://www.in.gov/courts/appeals/judges/pete-foley |

### Second District
| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Dana J. Kenworthy | Presiding Judge | January 16, 2023 | https://www.in.gov/courts/appeals/judges/dana-kenworthy |
| Cale J. Bradford | Judge | August 1, 2007 | https://www.in.gov/courts/appeals/judges/cale-bradford |
| Robert R. Altice, Jr. | Judge | September 2, 2015 | https://www.in.gov/courts/appeals/judges/robert-altice |

### Third District
| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Elizabeth F. Tavitas | Chief Judge | August 6, 2018 | https://www.in.gov/courts/appeals/judges/elizabeth-tavitas |
| Paul D. Mathias | Judge | March 30, 2000 | https://www.in.gov/courts/appeals/judges/paul-mathias |
| Stephen E. Scheele | Judge | January 8, 2025 | https://www.in.gov/courts/appeals/judges/stephen-scheele |

### Fourth District
| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Mary A. DeBoer | Presiding Judge | October 15, 2024 | https://www.in.gov/courts/appeals/judges/mary-deboer |
| Melissa S. May | Judge | April 9, 1998 | https://www.in.gov/courts/appeals/judges/melissa-may |
| Rudolph R. Pyle, III | Judge | August 27, 2012 | https://www.in.gov/courts/appeals/judges/rudolph-pyle |

### Fifth District
| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Paul A. Felix | Presiding Judge | July 28, 2023 | https://www.in.gov/courts/appeals/judges/paul-felix |
| Nancy H. Vaidik | Judge | February 7, 2000 | https://www.in.gov/courts/appeals/judges/nancy-vaidik |
| Elaine B. Brown | Judge | May 5, 2008 | https://www.in.gov/courts/appeals/judges/elaine-brown |

### Senior Judges
| Name | Senior Since | Bio URL |
|------|--------------|---------|
| John G. Baker | August 1, 2020 | https://www.in.gov/courts/appeals/judges/john-baker |
| Terry A. Crone | November 5, 2024 | https://www.in.gov/courts/appeals/judges/terry-crone |
| Edward W. Najam, Jr. | August 1, 2022 | https://www.in.gov/courts/appeals/judges/edward-najam/ |
| Margret G. Robb | June 19, 2023 | https://www.in.gov/courts/appeals/judges/margret-robb |
| Randall T. Shepard | March 15, 2012 | https://www.in.gov/courts/supreme/justices/randall-shepard |

---

## Current Judge - Indiana Tax Court

| Name | Position | Appointed | Bio URL |
|------|----------|-----------|---------|
| Justin L. McAdam | Tax Court Judge | July 2023 | https://www.in.gov/courts/tax/justin-mcadam/ |

---

## Jurisdiction

### Indiana Supreme Court
- Final appellate jurisdiction over all cases
- Original jurisdiction in admission and discipline of attorneys
- Promulgation of court rules
- Administrative supervision of all Indiana courts
- Mandatory jurisdiction in death penalty cases, lawyer discipline, and certain certified questions

### Court of Appeals of Indiana
- Appellate jurisdiction over most civil and criminal appeals
- Hears appeals from trial courts and some state agencies
- Cases heard in three-judge panels (randomly assigned)
- Decisions reviewable by Supreme Court via transfer

### Indiana Tax Court
- Exclusive jurisdiction over Indiana tax law cases
- Initial appeals from Indiana Department of State Revenue
- Appeals from Indiana Board of Tax Review
- Certain appeals from Department of Local Government Finance

---

## Opinion Types and Publication

### Opinion Categories
1. **Published Opinions**: Precedential decisions with full citation
2. **Memorandum Decisions**: Non-precedential decisions (can be filtered in search)
3. **Orders**: Administrative and procedural orders
4. **Transfer Dispositions**: Supreme Court decisions on transfer requests

### Case Categories
- Criminal
- Civil
- Juvenile
- Tax (Tax Court only)
- Original Actions
- Certified Questions

### Publication
- Cited opinions published in:
  - North Eastern Reporter (West Publishing)
  - Indiana Reports (historical)
- All opinions available on the decisions portal
- Memorandum decisions labeled "Not for publication"

---

## Access Restrictions

### No Login Required
- Public access to all published opinions
- Oral argument schedules and archived videos
- Judge biographies
- Court rules

### myCase Portal
- Public access to most case information
- Some records restricted (sealed cases, juvenile matters)
- No registration required for basic searches

### Data Mining Prohibited
- Supreme Court rules prohibit data mining from court websites
- Users found in violation may be blocked
- Respectful scraping recommended

---

## Technical Implementation Notes

### Decisions Portal
- AngularJS single-page application
- API-based data retrieval
- JSON request/response format
- Pagination via API parameters

### Opinion URL Structure
- PDFs accessed via API endpoint with encoded IDs
- IDs are base64-like encoded strings
- No predictable URL pattern for direct PDF access

### myCase Portal
- Modern web application
- Case tokens encoded in base64 format
- Real-time case information

### Oral Arguments
- ASP.NET WebForms application
- Table-based pagination
- Video streaming via I-Light
- Archives from 2001 to present

### Scraping Considerations
- JavaScript required for decisions portal
- API endpoints can be called directly with proper parameters
- Court IDs: 9510 (Supreme), 9530 (Appeals), 9550 (Tax)
- Pagination handled via API
- Rate limiting recommended per terms of use

---

## Example Cases

### Supreme Court
- **25S-CR-00303** - Carlos Tacio Ortiz v. State of Indiana (oral argument Jan 22, 2026)
- **25S-CT-00332** - David Noble v. Fairview Mobile Home Community (oral argument Jan 22, 2026)
- **24A-DN-01655** - Jackie L. Bowen v. Mark J. Bowen

### Court of Appeals
- **25A-CR-00675** - Devon Makel Jones v. State of Indiana (Criminal)
- **25A-PL-01096** - Asher B Hill v. Sara Bedwell, et al. (Civil)
- **25A-JC-1315** - E.B. v. IDCS (Juvenile)

### Tax Court
- **19T-TA-00021** - Convention Headquarters Hotels, LLC v. Marion County Assessor
- **24T-TA-00018** - United Parcel Service, Inc. v. Ind. Dep't of State Revenue

### Case Number Format
- Supreme Court: `{YY}S-{Type}-{Number}` (e.g., 25S-CR-00303)
- Court of Appeals: `{YY}A-{Type}-{Number}` (e.g., 25A-CR-00675)
- Tax Court: `{YY}T-{Type}-{Number}` (e.g., 24T-TA-00018)
- Trial Court: `{County#}{Court}{Year}-{Type}-{Number}` (e.g., 48C04-2312-F1-003574)

---

## Recommended Scraper Architecture

### 1. Opinion Listing Scraper
**Source**: Decisions API (`https://public.courts.in.gov/decisions`)

**Approach**:
1. Query API with appropriate court ID and date range
2. Parse JSON response for opinion metadata
3. Extract opinion IDs and construct download URLs
4. Download PDFs via API endpoint

**Data Available**:
- Case number (appellate and trial court)
- Case name/style
- Opinion date
- Court (Supreme, Appeals, Tax)
- Case category
- Authoring judge
- Decision type (opinion vs memorandum)
- Disposition (Affirmed, Reversed, etc.)
- Concurring/dissenting judges
- County of origin
- PDF download ID

### 2. Oral Arguments Scraper
**Source**: Arguments Portal (`https://mycourts.in.gov/arguments/`)

**Approach**:
1. Query with court, year, and month filters
2. Parse HTML table for scheduled/archived arguments
3. Extract case information and video links

**Data Available**:
- Case title
- Scheduled date/time
- Court (Supreme, Appeals, Tax)
- County of origin
- Video archive link

### 3. Case Information Scraper
**Source**: myCase Portal (`https://mycase.in.gov/`)

**Approach**:
1. Search by case number or party name
2. Navigate to case summary
3. Extract detailed case information

**Data Available**:
- Full case history
- Party information
- Attorney information
- Docket entries
- Related cases

---

## Additional Resources

- **Court Rules**: https://rules.incourts.gov/Content/index.htm
- **FAQs**: https://courts-ingov.zendesk.com/hc/en-us/categories/115000874788-Judicial-System-Indiana
- **Email Subscriptions**: https://www.in.gov/courts/subscribe
- **Court Calendar**: https://events.in.gov/courts
- **YouTube Channel**: https://www.youtube.com/incourts
- **Twitter/X**: https://twitter.com/incourts
- **Flickr (Court Photos)**: https://www.flickr.com/photos/incourts/sets/

---

## Contact Information

### Supreme Court
- Phone: 317-232-2540
- Fax: 317-232-8372
- Media Contact: Kathryn Dolan (317-232-2542)
- Email: kathryn.dolan@courts.in.gov

### Court of Appeals
- Court Administrator: Larry L. Morris (317-232-6906)
- Director of Communications: Anne Fuchs (317-234-4859)

### Tax Court
- Court Administrator: Karyn Graves (317-232-4694)

### Clerk of the Appellate Courts
- Main Office: 317-232-1930
- Records: 317-232-7225
- Website: http://courts.in.gov/cofc
