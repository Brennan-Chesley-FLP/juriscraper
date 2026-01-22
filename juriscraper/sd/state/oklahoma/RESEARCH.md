# Oklahoma Courts Research

## Court Structure

Oklahoma has a unique appellate court structure with two courts of last resort - one for civil matters and one for criminal matters.

### 1. Supreme Court of Oklahoma
- **Website**: https://oksc.oscn.net/
- **OSCN Portal**: https://www.oscn.net/
- Highest court for civil matters in Oklahoma
- 9 Justices (1 Chief Justice + 1 Vice-Chief Justice + 7 Justices)
- Justices are appointed by the Governor from a list of nominees selected by the Judicial Nominating Commission
- Justices face retention elections after initial appointment
- Located at Oklahoma Judicial Center, 2100 N. Lincoln Blvd., Suite 1, Oklahoma City, OK 73105

#### Jurisdiction
- Final appellate court for all civil cases
- Original jurisdiction for writs of mandamus, prohibition, habeas corpus, and other extraordinary writs
- Supervisory authority over all state courts
- Attorney and judge discipline matters
- Bar admission matters
- Certified questions of state law from federal courts

### 2. Court of Criminal Appeals (OCCA)
- **Website**: https://www.okcca.net/
- Highest court for criminal matters in Oklahoma
- 5 Judges (1 Presiding Judge + 1 Vice-Presiding Judge + 3 Judges)
- Judges are appointed similar to Supreme Court justices
- Located at Oklahoma Judicial Center, 2100 N. Lincoln Blvd., Suite 2, Oklahoma City, OK 73105-4907
- Phone: 405-556-9606 or 405-556-9627

#### Jurisdiction
- Final appellate court for all criminal cases
- Death penalty appeals
- Post-conviction relief in criminal matters
- Juvenile delinquency appeals

### 3. Court of Civil Appeals (COCA)
- **Overview**: Intermediate appellate court for civil matters
- 12 Judges organized by districts
- Judges elected from judicial districts
- Cases heard by 3-judge panels
- Biographies available at: https://www.oscn.net/static/coca-biographies.pdf

### 4. District Courts
- **Courts by County**: https://www.oscn.net/courts/
- 77 counties with district courts
- General jurisdiction trial courts
- Handle civil, criminal, family, juvenile, and probate matters

---

## Key URLs and URL Patterns

### Main Portal
- **OSCN Home**: https://www.oscn.net/
- **Supreme Court**: https://oksc.oscn.net/
- **Court of Criminal Appeals**: https://www.okcca.net/

### Opinion/Case Search Systems
- **Legal Research Library**: https://www.oscn.net/applications/oscn/start.asp?viewType=LIBRARY
- **Oklahoma Cases Index**: https://www.oscn.net/applications/oscn/index.asp?ftdb=STOKCS&level=1
- **Search Page**: https://www.oscn.net/applications/oscn/search.asp
- **Advanced Search**: https://www.oscn.net/applications/oscn/search.asp?simple=true
- **QuickCase (Citations)**: https://www.oscn.net/applications/oscn/QuickCase.asp

### Case Databases (ftdb codes)
- `STOKCS` - All Oklahoma Cases
- `STOKCSSC` - Oklahoma Supreme Court Cases (1890-present)
- `STOKCSCR` - Oklahoma Court of Criminal Appeals Cases (1908-present)
- `STOKCSCV` - Oklahoma Court of Civil Appeals Cases (1968-present)
- `STOKCSJU` - Oklahoma Court on the Judiciary

### Docket Search
- **Docket Search**: https://www.oscn.net/dockets/Search.aspx
- **Appellate Dockets**: https://www.oscn.net/dockets/Search.aspx#appellate

### Recent Decisions
- **Recent Appellate Opinions**: https://www.oscn.net/decisions/
- **Supreme Court Recent (30 days)**: https://www.oscn.net/decisions/ok/30
- **OCCA Recent (30 days)**: https://www.oscn.net/decisions/ok-cr/30
- **COCA Recent**: https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKCSCV

### Oral Arguments
- **Supreme Court Oral Arguments**: https://www.oscn.net/oral-arguments/
- **Supreme Court Calendar**: https://www.oscn.net/calendar/
- **OCCA Hearings**: Listed on https://www.okcca.net/ homepage

---

## Opinion URL Patterns

### Case Index by Year
- **Pattern**: `https://www.oscn.net/applications/oscn/Index.asp?ftdb={database}&year={year}&level=1`
- **Supreme Court 2026**: `https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKCSSC&year=2026&level=1`
- **Criminal Appeals 2026**: `https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKCSCR&year=2026&level=1`
- **Civil Appeals 2026**: `https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKCSCV&year=2026&level=1`

### Individual Opinion URLs
- **Pattern**: `https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID={id}`
- **Example**: `https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=551118`
- CiteID is a unique numeric identifier for each opinion

### Citation Format
- **Supreme Court**: `YYYY OK N` (e.g., `2026 OK 1`)
- **Criminal Appeals**: `YYYY OK CR N` (e.g., `2026 OK CR 1`)
- **Civil Appeals**: `YYYY OK CIV APP N` (e.g., `2026 OK CIV APP 1`)

---

## Case Docket URL Patterns

### Appellate Case Information
- **Pattern**: `https://www.oscn.net/dockets/GetCaseInformation.aspx?db=appellate&number={casenumber}`
- **Example**: `https://www.oscn.net/dockets/GetCaseInformation.aspx?db=appellate&number=123238`

### District Court Case Information
- **Pattern**: `https://www.oscn.net/dockets/GetCaseInformation.aspx?db={county}&number={casenumber}`
- County codes are lowercase county names (e.g., `tulsa`, `oklahoma`, `cleveland`)

### Docket Document URLs
- **PDF Pattern**: `https://www.oscn.net/dockets/GetDocument.aspx?ct=appellate&bc={documentid}&cn={casenumber}&fmt=pdf`
- **TIFF Pattern**: `https://www.oscn.net/dockets/GetDocument.aspx?ct=appellate&cn={casenumber}&bc={documentid}&fmt=tif`
- **Example**: `https://www.oscn.net/dockets/GetDocument.aspx?ct=appellate&bc=1064051432&cn=MA-123238&fmt=pdf`

### Case Number Formats
- **Supreme Court**: `{number}` (e.g., `123238`) or `MA-{number}` for mandamus
- **Criminal Appeals**: Various prefixes like `F-`, `C-`, `PC-`, `D-`, `S-`, `J-`
- **Civil Appeals**: Various prefixes

---

## Current Justices - Supreme Court

| Name | Position | Bio URL |
|------|----------|---------|
| Dustin P. Rowe | Chief Justice | https://oksc.oscn.net/justices/dustin-p-rowe/ |
| Dana Kuehn | Vice-Chief Justice | https://oksc.oscn.net/justices/dana-kuehn/ |
| James R. Winchester | Justice | https://oksc.oscn.net/justices/james-r-winchester/ |
| James E. Edmondson | Justice | https://oksc.oscn.net/justices/james-e-edmondson/ |
| Douglas L. Combs | Justice | https://oksc.oscn.net/justices/douglas-l-combs/ |
| Noma Gurich | Justice | https://oksc.oscn.net/justices/noma-gurich/ |
| Richard Darby | Justice | https://oksc.oscn.net/justices/richard-darby/ |
| M. John Kane IV | Justice | https://oksc.oscn.net/justices/john-kane-iv/ |
| Travis Jett | Justice | https://oksc.oscn.net/justices/justice-travis-jett/ |

---

## Current Judges - Court of Criminal Appeals

| Name | Position | Bio URL |
|------|----------|---------|
| Gary Lumpkin | Presiding Judge | http://okcca.net/judges/gary-l-lumpkin/ |
| William J. Musseman | Vice-Presiding Judge | http://okcca.net/judges/william-musseman/ |
| Robert Hudson | Judge | http://okcca.net/judges/robert-l-hudson/ |
| David Lewis | Judge | http://okcca.net/judges/david-b-lewis/ |
| Scott Rowland | Judge | http://okcca.net/judges/scott-rowland/ |

---

## Current Judges - Court of Civil Appeals

| Name | Bio URL |
|------|---------|
| Barnes, Deborah | https://www.oscn.net/static/coca-biographies.pdf#page=2 |
| Bell, Robert D. | https://www.oscn.net/static/coca-biographies.pdf#page=4 |
| Blackwell, Gregory C. | https://www.oscn.net/static/coca-biographies.pdf#page=5 |
| Downing, Timothy J. | https://www.oscn.net/static/coca-biographies.pdf#page=6 |
| Fischer, John F. | https://www.oscn.net/static/coca-biographies.pdf#page=7 |
| Goree, Brian Jack | https://www.oscn.net/static/coca-biographies.pdf#page=8 |
| Hixon, Stacie L. | https://www.oscn.net/static/coca-biographies.pdf#page=9 |
| Huber, James | https://www.oscn.net/static/coca-biographies.pdf#page=10 |
| Mitchell, III, E. Bay | https://www.oscn.net/static/coca-biographies.pdf#page=11 |
| Prince, Thomas E. | https://www.oscn.net/static/coca-biographies.pdf#page=12 |
| Swinton, Barbara | https://www.oscn.net/static/coca-biographies.pdf#page=13 |
| Wiseman, Jane P. | https://www.oscn.net/static/coca-biographies.pdf#page=15 |

---

## Case Types

### Supreme Court
- Civil appeals from Court of Civil Appeals
- Original jurisdiction (mandamus, prohibition, habeas corpus, quo warranto)
- Certified questions from federal courts
- Bar discipline matters
- Judicial discipline matters
- Tax Commission appeals
- Corporation Commission appeals
- Workers' Compensation Commission appeals

### Court of Criminal Appeals
- Felony appeals
- Misdemeanor appeals
- Death penalty cases
- Post-conviction relief
- Habeas corpus (criminal)
- Juvenile certification appeals
- State appeals/reserved questions of law

---

## Opinion Types and Publication

### Published Opinions
- Full opinions with precedential value
- Available through OSCN database
- Assigned official citations (YYYY OK N format)

### Unpublished Opinions
- Available at: https://www.oscn.net/applications/oscn/Unpublished.asp
- Limited precedential value
- Still searchable and accessible

### Orders
- Supreme Court Orders: https://www.oscn.net/orders/
- Procedural rulings and administrative orders

---

## Access Restrictions

### No Login Required
- All appellate court opinions (Supreme Court, OCCA, COCA)
- Docket search for all courts
- Case information pages
- Document downloads (PDF and TIFF)
- Justice/Judge biographies
- Oral argument videos (via Vimeo)
- Legal research library

### Login Required
- E-Filing system: https://efile.oscn.net/
- E-Payments: https://pay.oscn.net/epayments/

### Rate Limiting
- No apparent CAPTCHA or aggressive rate limiting observed
- Standard best practices recommended for scraping

---

## Oral Arguments

### Supreme Court
- **URL**: https://www.oscn.net/oral-arguments/
- Videos hosted on Vimeo
- Calendar available at: https://www.oscn.net/calendar/
- Arguments held in Courtroom of Oklahoma Supreme Court, second floor of State Capitol

### Court of Criminal Appeals
- Upcoming hearings listed on homepage: https://www.okcca.net/
- Livestream available via Vimeo
- Hearings held at Oklahoma Judicial Center, 2100 N. Lincoln Blvd., Third Floor

---

## Technical Implementation Notes

### Website Architecture
- **Primary Domain**: www.oscn.net
- **Supreme Court Site**: oksc.oscn.net (WordPress)
- **OCCA Site**: www.okcca.net (WordPress)
- **Docket System**: ASP.NET WebForms application
- **Legal Research**: ASP.NET WebForms application
- Documents available in PDF and TIFF formats

### Search System
- Full-text search available
- Supports citation lookup (QuickCase)
- Batch citation processing available
- Filter by database, year, court

### Docket System Features
- Search by case number, party name, attorney
- Filter by court, case type, date range
- Traffic citation search (district courts)
- Lower court case number search (appellate)

### Scraping Approach
1. **Recent Opinions**: Use decision index pages with year filter
   - `https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKCSSC&year=2026&level=1`
2. **Historical Data**: Paginate through index by year
3. **Docket Information**: Use GetCaseInformation.aspx with case number
4. **Documents**: Download via GetDocument.aspx with document ID

### Data Availability
- **Supreme Court Opinions**: 1890 to present
- **Court of Criminal Appeals Opinions**: 1908 to present
- **Court of Civil Appeals Opinions**: 1968 to present
- **Docket Information**: Comprehensive for appellate and district courts

---

## Example URLs

```
# Legal Research Library
GET https://www.oscn.net/applications/oscn/start.asp?viewType=LIBRARY

# Supreme Court cases index
GET https://www.oscn.net/applications/oscn/index.asp?ftdb=STOKCSSC&level=1

# Supreme Court 2026 cases
GET https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKCSSC&year=2026&level=1

# Individual opinion by CiteID
GET https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=551118

# Docket search page
GET https://www.oscn.net/dockets/Search.aspx

# Appellate case docket
GET https://www.oscn.net/dockets/GetCaseInformation.aspx?db=appellate&number=123238

# Docket document PDF
GET https://www.oscn.net/dockets/GetDocument.aspx?ct=appellate&bc=1064051432&cn=MA-123238&fmt=pdf

# Supreme Court oral arguments
GET https://www.oscn.net/oral-arguments/

# Justices page
GET https://oksc.oscn.net/justices/

# OCCA homepage with recent decisions
GET https://www.okcca.net/

# Recent appellate decisions
GET https://www.oscn.net/decisions/
```

---

## Example Cases

### Recent Supreme Court Cases (2026)
- **Tobacco Settlement Endowment Trust Fund v. Stitt, et al.** - 2026 OK 1 (Case No. MA-123238) - Original jurisdiction mandamus case
- **NonDoc Media v. State ex rel. Board of Regents** - 2026 OK 2 (Case No. 122808)

### Recent Court of Criminal Appeals Cases (2026)
- **Zou v. State** - 2026 OK CR 1 - Cultivation and trafficking conviction

---

## Contact Information

### Supreme Court of Oklahoma
- **Address**: 2100 N. Lincoln Blvd., Suite 1, Oklahoma City, OK 73105
- **Website**: https://oksc.oscn.net/

### Court of Criminal Appeals
- **Address**: 2100 N. Lincoln Blvd., Suite 2, Oklahoma City, OK 73105-4907
- **Phone**: 405-556-9606 or 405-556-9627
- **Website**: https://www.okcca.net/

### Clerk of the Appellate Courts
- **Address**: 2100 N. Lincoln Blvd., Suite 4, Oklahoma City, OK 73105
- **Phone**: 405-556-9400

### OSCN Contact
- **Contact Form**: https://www.oscn.net/applications/oscn/SimpleHelp.asp?HelpContextID=84

---

## Notes

1. **Dual Court of Last Resort**: Oklahoma is one of only two states (along with Texas) that has separate courts of last resort for civil and criminal matters.

2. **OSCN System**: The Oklahoma State Courts Network (OSCN) is a comprehensive portal providing access to all state court information, including opinions, dockets, statutes, and court rules.

3. **Historical Coverage**: The OSCN database has extensive historical coverage, with Supreme Court cases back to 1890 (Oklahoma statehood was 1907, but territorial cases are included).

4. **Document Formats**: Docket documents are available in both PDF and TIFF formats, with the PDF being more accessible for modern use.

5. **Mailing List**: OSCN provides email notification service for new appellate opinions at https://www.oscn.net/mailinglist/

6. **Judicial Nominating Commission**: Oklahoma uses a merit selection system for appellate judges, with the Governor appointing from nominees selected by the Judicial Nominating Commission, followed by retention elections.

7. **District Maps**:
   - Supreme Court Districts: http://www.oscn.net/sites/judicialnominatingcommission/documents/Supreme-Court-Judicial-Districts.pdf
   - OCCA Districts: http://www.oscn.net/sites/judicialnominatingcommission/documents/Criminal%20Appeals.pdf
   - COCA Districts: https://www.oscn.net/jnc/doc/court-of-civil-appeals-electoral-districts.pdf

8. **Judicial Pictorial Directory**: Available at http://www.oscn.net/static/JudicialDirectory.pdf

9. **E-Filing**: Mandatory e-filing through https://efile.oscn.net/

10. **API Considerations**: The OSCN system uses traditional ASP.NET web forms without a public API, so scraping requires parsing HTML responses.
