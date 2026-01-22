# Arizona Appellate Courts Scraper Research

## Research Date: 2026-01-22
## Verification Status: Verified via browser testing

## 1. Overview

Arizona has a unified statewide judicial system with separate websites for the Supreme Court and Court of Appeals opinions, plus a public case access system.

### Courts
- **Arizona Supreme Court** (7 justices) - Court ID: `ariz`
- **Court of Appeals, Division One** (19 judges, Phoenix) - Court ID: `arizctapp`
- **Court of Appeals, Division Two** (9 judges, Tucson) - Court ID: `arizctapp2`

### Data Types Available
1. **Opinions** - Full opinions, memorandum decisions, decision orders
2. **Cases/Dockets** - Active case lists by type, docket entries
3. **Oral Arguments** - Live streaming and archived video (Granicus)

## 2. Official Court Websites

### Main Sites
| Site | URL | Status |
|------|-----|--------|
| Main Court Website | https://www.azcourts.gov/ | Verified |
| Supreme Court Section | https://www.azcourts.gov/AZ-Supreme-Court | Verified |
| Court of Appeals Div 1 | https://coa1.azcourts.gov/ | Verified |
| Court of Appeals Div 2 | http://www.appeals2.az.gov | Referenced |
| Opinion Search (SC) | https://www.azcourts.gov/opinions | Verified |
| Decision Search (COA1) | https://coa1.azcourts.gov/Decisions/Search-Decisions | Verified |
| Meet the Justices | https://www.azcourts.gov/MeettheJustices | Verified |
| Public Case Access | https://apps.azcourts.gov/publicaccess | Verified |
| Appellate Case Status | https://www.azcourts.gov/appellatecourtcases | Verified |
| eAccess Portal | https://eaccess.azcourts.gov/ | Referenced |
| Oral Arguments Video | https://www.azcourts.gov/AZ-Supreme-Court/Live-Archived-Video | Verified |

## 3. Court Structure

### Supreme Court Justices (7 total)

| Justice | Role | Appointed | Bio URL |
|---------|------|-----------|---------|
| **Ann A. Scott Timmer** | Chief Justice | 2012 (CJ 2024) | [Bio](https://www.azcourts.gov/meetthejustices/Chief-Justice-Ann-A-Scott-Timmer) |
| **John R. Lopez IV** | Vice Chief Justice | Nov 2016 | [Bio](https://www.azcourts.gov/meetthejustices/Vice-Chief-Justice-John-R-Lopez-IV) |
| Clint Bolick | Justice | Jan 2016 | [Bio](https://www.azcourts.gov/meetthejustices/Justice-Clint-Bolick) |
| James P. Beene | Justice | 2019 | [Bio](https://www.azcourts.gov/meetthejustices/Justice-James-Beene) |
| William G. Montgomery | Justice | 2019 | [Bio](https://www.azcourts.gov/meetthejustices/Justice-William-G-Montgomery) |
| Kathryn H. King | Justice | 2021 | [Bio](https://www.azcourts.gov/meetthejustices/Justice-Kathryn-H-King) |
| Maria Elena Cruz | Justice | 2024 (bench since 2005) | [Bio](https://www.azcourts.gov/MeetTheJustices) |

### Court of Appeals Division One (19 judges, Phoenix)
- Chief Judge: David B. Gass
- Has statewide jurisdiction for Industrial Commission, unemployment compensation, and Tax Court appeals
- Location: 1501 W. Washington St., Phoenix, AZ 85007
- Phone: (602) 452-6700
- Email: inform@appeals.az.gov

### Court of Appeals Division Two (9 judges, Tucson)
- Website: http://www.appeals2.az.gov

## 4. Opinion Search System

### Supreme Court Opinions

**Search URL**: `https://www.azcourts.gov/opinions/Memorandum-Decisions/Search-Opinions-Memo-Decs`

**URL Parameters**:
- `year=YYYY` - Filter by year (e.g., 2025, 2024)
- `court=999` - All courts (default shows Arizona Supreme Court)

**Year-Based Browse URLs**:
- Pattern: `/opinions/Memorandum-Decisions/Search-Opinions-Memo-Decs?year=YYYY&court=999`
- Available years: 1998-2026 (pre-2002 uses different URL format)
- Historical (pre-2002): `/opinions/Memorandum-Decisions/YYYY-Opinions-Memo-Decs`

### Search Filters Available

| Filter | Options |
|--------|---------|
| Court | Arizona Supreme Court, Court of Appeals Div 1 |
| Decision Type | Decision Order, Memorandum, Opinion |
| Case Type | Civil, Criminal, Judicial Conduct (Circuit), State Bar, Water Case |
| Case Sub-Type | Appeal, Certified Question, Disciplinary, Election Appeal, Interlocutory Review, Miscellaneous, Petition for Review, Post Conviction, Reinstatement, Special Action, Transfer Appeal |
| Judge | Free text search |
| Judge Involvement | Author, Concur, Concur in part, Dissent, etc. |
| Constitutionality | Checkbox for constitutional rulings |

### Court of Appeals Division One Opinions

**Search URL**: `https://coa1.azcourts.gov/Decisions/Search-Decisions`

**Additional Case Types (COA1 only)**:
- Corporation Commission
- Habeas Corpus
- Industrial Commission
- Juvenile
- Mental Health
- Special Action
- Tax Appeal
- Unemployment Board

### Full-Text Search
- URL: `/opinions/Opinions-Custom-Search` (Supreme Court)
- URL: `/coa1/SearchDecisionDocumentText.aspx` (Division One)

## 5. Opinion PDF URLs

### URL Pattern
Supreme Court: `/Portals/0/OpinionFiles/Supreme/YYYY/[CaseNumber].pdf`

**Examples**:
- `https://www.azcourts.gov/Portals/0/OpinionFiles/Supreme/2025/CR-240064-PR.pdf`
- `https://www.azcourts.gov/Portals/0/OpinionFiles/Supreme/2025/CV240220TAP.pdf`

### Case Number Formats

| Court | Format | Examples |
|-------|--------|----------|
| Supreme Court (Criminal) | CR-YY-NNNN-PR | CR-24-0064-PR |
| Supreme Court (Civil) | CV-YY-NNNN-PR | CV-24-0220-T/AP |
| Court of Appeals Div 1 | 1 CA-XX YY-NNNN | 1 CA-CV 23-0123 |
| Court of Appeals Div 2 | 2 CA-XX YY-NNNN | 2 CA-CR 24-0456 |

## 6. Opinion Data Structure

Each opinion in search results includes:
- **Filing Date** - Date decision was filed
- **Case Number** - Unique identifier (links to PDF)
- **Case Title** - Party names (links to PDF)
- **Decision Type** - Opinion, Memorandum, Decision Order
- **Judges** - List with involvement type (Author, Concur, Dissent, etc.)
- **Constitutionality Summary** - (when applicable) Description of constitutional ruling

## 7. Appellate Case Status System

### URLs by Court

| Court | URL |
|-------|-----|
| Appellate Home | https://www.azcourts.gov/appellatecourtcases |
| Supreme Court | https://www.azcourts.gov/appellatecourtcases/ASC |
| Division One | https://www.azcourts.gov/appellatecourtcases/COA1 |
| Division Two | https://www.azcourts.gov/appellatecourtcases/COA2 |

### Active Case Lists (Division One)

| Code | Type | Count (Jan 2026) |
|------|------|------------------|
| CC | Corporation Commission | 4 |
| CR | Criminal | 527 |
| CV | Civil | 673 |
| HC | Habeas Corpus | 2 |
| IC | Industrial Commission | 32 |
| JV | Juvenile | 120 |
| MH | Mental Health | 67 |
| SA | Special Action | 160 |
| TX | Tax Appeal | 7 |
| UB | Unemployment Board | 9 |

**Case List URL Pattern**: `/appellatecourtcases/COA1/Cases/stage_1CA_[TYPE].htm`

## 8. Public Case Access System

**URL**: `https://apps.azcourts.gov/publicaccess`

### Features
- Case Search (caselookup.aspx)
- Minute Entry Search (minutes.aspx)
- Case Notification (notify/login.aspx)
- Covers 177 of 184 Arizona courts

### Access Restrictions
- **CAPTCHA Required** - Must solve CAPTCHA before searching
- **Weekly Updates** - Updated each Friday to reflect Wednesday's data
- **Excluded Cases**: Sealed cases, Orders of Protection, mental health, probate, juvenile delinquency
- **No Official Record** - Website is for informational purposes only

### eAccess Portal
- URL: https://eaccess.azcourts.gov/
- Superior Court criminal and civil documents only
- Separate from appellate case system

## 9. Oral Arguments

### Live & Archived Video

**URL**: `https://www.azcourts.gov/AZ-Supreme-Court/Live-Archived-Video`
**Livestream**: `https://www.azcourts.gov/AZ-Supreme-Court/Livestream`

### Platform
- Hosted on Granicus: `supremestateaz.granicus.com`
- Archives available from 2006 to present
- Includes Case Summary (Agenda) and Opinion links when available

### RSS Feeds
- Agenda: `//supremestateaz.granicus.com/ViewPublisherRSS.php?view_id=11&mode=agendas`
- Minutes: `//supremestateaz.granicus.com/ViewPublisherRSS.php?view_id=11&mode=minutes`

### Calendar
- URL: `https://www.azcourts.gov/clerkofcourt/Oral-Argument-Calendar`
- Audio copies available from Clerk's Office: (602) 452-3396

### Court of Appeals Division One
- URL: `https://www.azcourts.gov/appellatecourtcases/COA1/Calendar`
- Oral argument audio available

## 10. Access Restrictions

### No Restrictions
- No login required for opinion search or download
- No date limitations for opinion searches (back to 1998 online)
- PDF downloads available directly without authentication
- No CAPTCHA on opinion search

### Restrictions
- Public case access requires CAPTCHA
- High-volume access requires contact with court for arrangements
- Some case types excluded from public access (sealed, juvenile, mental health)
- eAccess portal separate registration may be required

## 11. Technical Implementation Notes

### Key Observations

1. **Unified Opinion Database**
   - Supreme Court and Court of Appeals Div 1 share the same search interface
   - Court filter distinguishes between courts
   - Same PDF portal structure

2. **Case Number Parsing**
   - Supreme Court: `CV-YY-NNNN-XX` or `CR-YY-NNNN-XX`
   - Court of Appeals: `1 CA-XX YY-NNNN` format
   - PR = Petition for Review
   - T/AP = Transfer/Appeal

3. **Pagination**
   - Search results are paginated
   - 983 total Supreme Court records (as of research date)
   - 10 results per page default

4. **Judge Information**
   - Multiple judges listed per case with involvement type
   - Can filter by author, concur, dissent, etc.

5. **Constitutional Opinions**
   - Special tracking as required by Arizona Legislature
   - Includes summary of constitutional analysis

### Data Format
- HTML pages with structured tables
- PDF opinions with direct download URLs
- No JSON API observed
- Granicus platform for oral argument video

## 12. Recommended Scraping Strategy

### For Opinions
1. Use year-based browse URLs for bulk collection
2. Parse search results page for case metadata
3. Extract PDF URLs from case number/title links
4. Handle pagination for large result sets
5. Track constitutional opinions separately

### For Case Status
1. Navigate to appellate case status pages
2. Parse case type lists (HTML tables embedded in iframes)
3. Extract case details from linked pages
4. Monitor active case counts for changes

### For Oral Arguments
1. Use Granicus RSS feeds for new arguments
2. Parse archived video listings by year
3. Extract agenda/summary links for case details
4. Cross-reference with opinion data

## 13. Scraper Structure

```
juriscraper/sd/state/arizona/
├── __init__.py
├── ariz.py              # Supreme Court opinions
├── arizctapp.py         # Court of Appeals Division One opinions
├── arizctapp2.py        # Court of Appeals Division Two opinions
└── RESEARCH.md          # This file
```

### Key Features to Implement

1. **Opinion Scrapers**:
   - Scrape Supreme Court opinions
   - Scrape Court of Appeals Division One opinions
   - Handle memorandum decisions and decision orders
   - Parse constitutional opinion summaries

2. **Judge Information**:
   - Extract judge involvement (author, concur, dissent)
   - Match to current justice roster

3. **Oral Arguments** (optional):
   - Monitor Granicus RSS for new arguments
   - Link to case opinions when available

## 14. Example Cases

### Supreme Court Opinion
**CR-24-0064-PR: STATE OF ARIZONA v HON.GORDON/OWEN**
- Filed: December 12, 2025
- Type: Opinion
- Judges: Montgomery (Author), Timmer, Lopez, Beene, King (Concur), Bolick, Pelander (Dissent)
- PDF: https://www.azcourts.gov/Portals/0/OpinionFiles/Supreme/2025/CR-240064-PR.pdf

### Constitutional Decision
**CV-24-0220-T/AP: KNIGHT et al v FONTES et al**
- Filed: December 4, 2025
- Type: Opinion
- Constitutional Analysis: Retention election of Court of Appeals judges under A.R.S. § 12-120.02
- PDF: https://www.azcourts.gov/Portals/0/OpinionFiles/Supreme/2025/CV240220TAP.pdf

## 15. Contact Information

### Arizona Supreme Court
- Phone: (602) 452-3396
- Email: pasupport@courts.az.gov
- Location: 1501 W. Washington St., Phoenix, AZ 85007

### Court of Appeals Division One
- Phone: (602) 452-6700
- Email: inform@appeals.az.gov
- Location: State Courts Building, Phoenix

## 16. References

- Main website: https://www.azcourts.gov/
- Supreme Court: https://www.azcourts.gov/AZ-Supreme-Court
- Opinions: https://www.azcourts.gov/opinions
- Court of Appeals Div 1: https://coa1.azcourts.gov/
- Meet the Justices: https://www.azcourts.gov/MeettheJustices
- Public Case Access: https://apps.azcourts.gov/publicaccess
- Appellate Cases: https://www.azcourts.gov/appellatecourtcases
- Oral Arguments: https://www.azcourts.gov/AZ-Supreme-Court/Live-Archived-Video
- Rules Forum: https://www.azcourts.gov/Rules-Forum
- Case Summaries: https://www.azcourts.gov/casesummaries
