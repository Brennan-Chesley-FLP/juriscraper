# Oregon Courts Research

## Court Structure

Oregon has a unified court system with a Supreme Court as the highest court and a Court of Appeals as the intermediate appellate court.

### 1. Oregon Supreme Court
- **Website**: https://www.courts.oregon.gov/courts/appellate/supreme/
- Highest court in Oregon
- 7 Justices (1 Chief Justice + 6 Associate Justices)
- Justices are elected to 6-year terms
- Located at 1163 State Street, Salem, OR 97301
- Phone: 503-986-5555

#### Jurisdiction
- Final appellate court for all state courts
- Death penalty cases (direct appeal)
- Ballot title cases
- Lawyer discipline matters
- Tax Court cases
- Certified questions of state law
- Discretionary review of Court of Appeals decisions

### 2. Oregon Court of Appeals
- **Website**: https://www.courts.oregon.gov/courts/appellate/coa/
- Intermediate appellate court (created by statute in 1969)
- 13 Judges (1 Chief Judge + 12 Judges)
- Judges elected to 6-year terms
- Cases heard by 3-judge panels
- Receives virtually all appeals except those going directly to Supreme Court

#### Jurisdiction
- Appeals from circuit courts (trial courts)
- Judicial review of administrative agency decisions
- All appeals except death penalty, ballot title, lawyer discipline, and tax court cases

### 3. Oregon Tax Court
- **Website**: https://www.courts.oregon.gov/courts/tax/
- Specialized court for tax-related disputes
- Has a Regular Division and Magistrate Division
- Appeals go directly to Supreme Court

### 4. Circuit Courts (Trial Courts)
- 36 circuit courts (one per county)
- General jurisdiction trial courts
- **Directory**: https://www.courts.oregon.gov/courts/Pages/default.aspx

---

## Key URLs and URL Patterns

### Main Portal
- **Judiciary Home**: https://www.courts.oregon.gov/
- **Appellate Courts Home**: https://www.courts.oregon.gov/courts/appellate/
- **Supreme Court**: https://www.courts.oregon.gov/courts/appellate/supreme/
- **Court of Appeals**: https://www.courts.oregon.gov/courts/appellate/coa/

### Opinion Pages
- **Supreme Court Opinions**: https://www.courts.oregon.gov/publications/sc/Pages/default.aspx
- **Court of Appeals Opinions**: https://www.courts.oregon.gov/publications/coa/Pages/default.aspx
- **Tax Court Decisions**: https://www.courts.oregon.gov/publications/tax/Pages/default.aspx

### Digital Collection (State of Oregon Law Library)
- **Supreme Court Opinions**: https://cdm17027.contentdm.oclc.org/digital/search/collection/p17027coll3/order/dated/ad/desc
- **Court of Appeals Opinions**: https://cdm17027.contentdm.oclc.org/digital/search/collection/p17027coll5/order/dated/ad/desc
- **Tax Court Decisions**: https://cdm17027.contentdm.oclc.org/digital/search/collection/p17027coll6/order/dated/ad/desc

### Case Management System (ACMS Public Portal)
- **Portal Home**: https://trportal.courts.oregon.gov/portal/home
- **Case Search**: https://trportal.courts.oregon.gov/portal/search/case
- **Party Search**: https://trportal.courts.oregon.gov/portal/search/party
- **Calendar Search**: https://trportal.courts.oregon.gov/portal/search/calendar
- **Document Search**: https://trportal.courts.oregon.gov/portal/search/document

### Justices and Judges
- **Supreme Court Justices**: https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx
- **Court of Appeals Judges**: https://www.courts.oregon.gov/courts/appellate/coa/Pages/judges.aspx

### Oral Arguments
- **Supreme Court Calendar**: https://www.courts.oregon.gov/courts/appellate/go/Pages/sc-calendar.aspx
- **Court of Appeals Calendar**: https://www.courts.oregon.gov/courts/appellate/go/Pages/coa-calendar.aspx
- **Webcasting**: https://www.courts.oregon.gov/courts/appellate/media/Pages/webcasting.aspx

---

## Opinion URL Patterns

### Digital Collection (CONTENTdm)
The State of Oregon Law Library maintains a digital collection of opinions using CONTENTdm.

#### Collection IDs
- `p17027coll3` - Oregon Supreme Court Opinions
- `p17027coll5` - Oregon Court of Appeals Opinions
- `p17027coll6` - Oregon Tax Court Decisions
- `p17027coll1` - Oregon Court of Appeals Briefs
- `p17027coll2` - Oregon Supreme Court Briefs
- `p17027coll10` - Chief Justice Orders

#### Browse URL Pattern
```
https://cdm17027.contentdm.oclc.org/digital/search/collection/{collection}/order/dated/ad/desc
```

#### Individual Opinion URL Pattern
```
https://cdm17027.contentdm.oclc.org/digital/collection/{collection}/id/{id}/rec/{rec}
```

#### Direct PDF URL Pattern
```
https://ojd.contentdm.oclc.org/digital/custom/OJDRedirect?collection={collection}&identifier={case_number}.pdf
```
Example: `https://ojd.contentdm.oclc.org/digital/custom/OJDRedirect?collection=p17027coll3&identifier=S070647.pdf`

#### Search URL Pattern
```
https://cdm17027.contentdm.oclc.org/digital/search/collection/{collection}/searchterm/{term}/field/{field}/mode/{mode}/conn/and/order/dated/ad/desc
```

### Court Website Opinion Links
The courts.oregon.gov website links to opinions in the digital collection:
- Page icon links directly to PDF via OJDRedirect
- Case number links to search results in the digital collection

---

## Case Docket URL Patterns

### ACMS Public Portal
The Appellate Case Management System (ACMS) Public Portal uses Thomson Reuters Case Management Systems.

#### Case Search URL
```
https://trportal.courts.oregon.gov/portal/search/case
```

#### Search Results URL Pattern
```
https://trportal.courts.oregon.gov/portal/search/case/results?criteria=~(advanced~false~courtID~'{court_guid}~paging~(totalItems~0~itemsPerPage~25~page~1~sortBy~'caseHeader.filedDate~sortDesc~true)~case~(...))
```

#### Court GUIDs
- Oregon Supreme Court: `f28c1f7b-0af7-4462-b253-bd5371f86443`
- Oregon Court of Appeals: (different GUID)

#### Individual Case URL Pattern
```
https://trportal.courts.oregon.gov/portal/court/{court_guid}/case/{case_guid}
```
Example: `https://trportal.courts.oregon.gov/portal/court/f28c1f7b-0af7-4462-b253-bd5371f86443/case/981582bb-2eb5-49ad-a6f0-48c7a5bf8fa8`

### Case Number Format
- **Supreme Court**: `SNNNNNN` (e.g., S072593, S070647)
- **Court of Appeals**: `ANNNNNN` (e.g., A123456)

---

## Current Justices - Supreme Court

| Position | Name | Title | Bio URL |
|----------|------|-------|---------|
| Chief Justice | Hon. Meagan A. Flynn | Chief Justice | https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx |
| Justice | Hon. Stephen K. Bushong | Justice | https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx |
| Justice | Hon. Bronson D. James | Justice | https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx |
| Justice | Hon. Aruna Masih | Justice | https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx |
| Justice | Hon. Rebecca A. Duncan | Justice | https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx |
| Justice | Hon. Christopher L. Garrett | Justice | https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx |
| Justice | Hon. Roger DeHoog | Justice | https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx |

---

## Current Judges - Court of Appeals

| Position | Name | Title |
|----------|------|-------|
| Position 12 | Hon. Erin C. Lagesen | Chief Judge |
| Position 1 | Hon. Ryan O'Connor | Judge |
| Position 2 | Hon. Megan L. Jacquot | Judge |
| Position 3 | Hon. Darleen Ortega | Judge |
| Position 4 | Hon. Robyn Aoyagi | Judge |
| Position 5 | Hon. Scott A. Shorr | Judge |
| Position 6 | Hon. James C. Egan | Judge |
| Position 7 | Hon. Steven R. Powers | Judge |
| Position 8 | Hon. Ramón A. Pagán | Judge |
| Position 9 | Hon. Jacqueline S. Kamins | Judge |
| Position 10 | Hon. Kristina Hellman | Judge |
| Position 11 | Hon. Anna M. Joyce | Judge |
| Position 13 | Hon. Douglas L. Tookey | Judge |

---

## Case Types

### Supreme Court Case Classifications
- Appeal - Civil - General
- Appeal - Civil - Other
- Appeal - Criminal - General
- Appeal - Criminal - Pretrial Felony - In Custody
- Appeal - Collateral Criminal - Habeas Corpus
- Appeal - Collateral Criminal - Post-Conviction
- Original Proceeding - Writ - Mandamus
- Original Proceeding - Writ - Habeas Corpus
- Professional Regulation - Bar Review - Resignation

### Court of Appeals Case Types
- Civil appeals
- Criminal appeals
- Administrative agency judicial review
- Worker's compensation appeals

---

## Opinion Types and Publication

### Supreme Court
- **Opinions**: Full written opinions with precedential value
- **Petitions for Review**: Lists of petitions granted/denied
- **Miscellaneous Dispositions**: Other court actions

### Court of Appeals
- **Published Opinions**: Full precedential opinions
- **Nonprecedential Memorandum Opinions**: Since May 2022, the Court of Appeals issues nonprecedential memorandum opinions (pursuant to ORAP changes)
- **Per Curiam Opinions**: Unsigned opinions

### Citation Format
- **Oregon Reports (Or)**: e.g., 374 Or 699
- **Oregon Court of Appeals Reports (Or App)**: e.g., 330 Or App 123
- Case numbers: S070647 (Supreme Court), A123456 (Court of Appeals)

---

## Access Restrictions

### No Login Required
- Opinion search on courts.oregon.gov
- Digital collection browsing and search
- ACMS Public Portal case search (basic information)
- Court calendars
- Justice/judge biographies

### Registered User Access
- ACMS eFiling
- Document viewing (for attorneys of record and parties)

### OJCIN OnLine (Paid Subscription)
- Full document access for all cases
- https://www.courts.oregon.gov/services/online/Pages/ojcin.aspx

### Access Levels in ACMS
1. **Anonymous**: View register of actions for public cases (no documents)
2. **Registered User**: Same + eFiling capability (no documents)
3. **Attorney Access**: Full access to cases where attorney of record + eFiling + eService
4. **Self-Represented Litigant**: Access to own cases + documents + eFiling + eService
5. **OJCIN Account**: Broad document access per subscription agreement

---

## Oral Arguments

### Webcasting
- Live streaming and archives available
- **URL**: https://www.courts.oregon.gov/courts/appellate/media/Pages/webcasting.aspx

### Calendars
- Supreme Court: https://www.courts.oregon.gov/courts/appellate/go/Pages/sc-calendar.aspx
- Court of Appeals: https://www.courts.oregon.gov/courts/appellate/go/Pages/coa-calendar.aspx

---

## Technical Implementation Notes

### Website Architecture
- **Primary Domain**: www.courts.oregon.gov (SharePoint-based)
- **Digital Collection**: cdm17027.contentdm.oclc.org (CONTENTdm by OCLC)
- **Case Management**: trportal.courts.oregon.gov (Thomson Reuters)

### Opinion Publication System
- Opinions published on courts.oregon.gov with links to digital collection
- PDF documents hosted on CONTENTdm
- Organized by "Advance Sheets" with date-based groupings

### ACMS Public Portal
- Thomson Reuters Case Management Systems
- Single-page application with hash-based routing
- Supports case, party, calendar, and document searches
- Multi-factor authentication for registered users

### Scraping Approach
1. **Recent Opinions**: Scrape courts.oregon.gov opinion pages for latest opinions
2. **Historical Opinions**: Use CONTENTdm digital collection with date sorting
3. **Case Information**: Use ACMS Public Portal case search
4. **PDF Downloads**: Use OJDRedirect URL pattern for direct PDF access

### Data Availability
- **Supreme Court Opinions**: Over 3,000 opinions in digital collection
- **Court of Appeals Opinions**: Extensive collection
- **Case Dockets**: Available via ACMS Public Portal
- **Oral Arguments**: Webcasts available

---

## Example URLs

```
# Supreme Court Opinions page
GET https://www.courts.oregon.gov/publications/sc/Pages/default.aspx

# Court of Appeals Opinions page
GET https://www.courts.oregon.gov/publications/coa/Pages/default.aspx

# Digital Collection - Supreme Court (sorted by date)
GET https://cdm17027.contentdm.oclc.org/digital/search/collection/p17027coll3/order/dated/ad/desc

# Digital Collection - Court of Appeals
GET https://cdm17027.contentdm.oclc.org/digital/search/collection/p17027coll5/order/dated/ad/desc

# Individual opinion in digital collection
GET https://cdm17027.contentdm.oclc.org/digital/collection/p17027coll3/id/16562/rec/1

# Direct PDF via OJDRedirect
GET https://ojd.contentdm.oclc.org/digital/custom/OJDRedirect?collection=p17027coll3&identifier=S070647.pdf

# ACMS Public Portal - Home
GET https://trportal.courts.oregon.gov/portal/home

# ACMS Case Search
GET https://trportal.courts.oregon.gov/portal/search/case

# ACMS Individual Case View
GET https://trportal.courts.oregon.gov/portal/court/f28c1f7b-0af7-4462-b253-bd5371f86443/case/981582bb-2eb5-49ad-a6f0-48c7a5bf8fa8

# Justices page
GET https://www.courts.oregon.gov/courts/appellate/supreme/Pages/justices.aspx

# Judges page
GET https://www.courts.oregon.gov/courts/appellate/coa/Pages/judges.aspx
```

---

## Example Cases

### Recent Supreme Court Cases (January 2026)
- **Crandall v. State of Oregon** - 374 Or 699 (S070647) - Opinion dated 2026-01-22
- **Moss Ranch, LLC v. Langell Valley Irrigation District** - S072593 - Original Proceeding - Writ - Mandamus
- **State of Oregon v. Wong** - S072589 - Criminal Appeal

### Recent Court of Appeals Cases
- Available via: https://www.courts.oregon.gov/publications/coa/Pages/default.aspx

---

## Contact Information

### Appellate Courts
- **Phone**: 503-986-5555
- **Fax**: 503-986-5560
- **Oregon Relay Service**: 711
- **Address**: Appellate Court Records Section, Supreme Court Building, 1163 State Street, Salem OR 97301
- **Hours**: 8 a.m. - 5 p.m. Monday-Friday (except state holidays)
- **Appellate Court Administrator**: Daniel W. Parr

### Technical Assistance (Online Services)
- **Phone**: 503-986-5582
- **Toll Free**: 1-877-826-5010
- **Email**: ETSDHelp@ojd.state.or.us
- **Hours**: M-F 7am - 5pm PST

### State of Oregon Law Library
- **Email**: state.law.library@ojd.state.or.us
- **Website**: https://soll.libguides.com

---

## Notes

1. **Two Opinion Systems**: Opinions are available both on courts.oregon.gov (organized by month/year) and in the CONTENTdm digital collection (searchable archive).

2. **CONTENTdm Platform**: The digital collection uses OCLC's CONTENTdm platform, which provides robust search and filtering capabilities.

3. **ACMS Portal**: The Appellate Case Management System is a modern web application but has access restrictions for document viewing.

4. **Nonprecedential Opinions**: Since May 2022, the Court of Appeals issues nonprecedential memorandum opinions per changes to the Oregon Rules of Appellate Procedure (ORAP).

5. **No Unified Search**: Unlike some states, Oregon does not have a single unified opinion search - users must use either the courts.oregon.gov pages or the digital collection.

6. **PDF Access**: Direct PDF access is available via the OJDRedirect endpoint without authentication for published opinions.

7. **Case Number Prefixes**: Supreme Court cases use "S" prefix, Court of Appeals use "A" prefix.

8. **Historical Coverage**: The digital collection contains opinions dating back many years; exact coverage start date varies by court.

9. **eService**: Registered attorneys and parties can receive electronic service of filings through the ACMS portal.

10. **Rate Limiting**: No apparent aggressive rate limiting observed on the digital collection, but standard best practices should be followed.
