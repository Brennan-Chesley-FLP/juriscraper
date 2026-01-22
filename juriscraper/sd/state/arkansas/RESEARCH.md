# Arkansas Appellate Courts Scraper Research

## Research Date: 2026-01-22
## Verification Status: Verified via browser testing

## 1. Overview

Arkansas has two appellate courts with a unified opinions database powered by Lexum's Norma platform at https://opinions.arcourts.gov/

### Courts
- **Arkansas Supreme Court** (7 justices) - Court ID: `arkansas`
- **Arkansas Court of Appeals** (12 judges across 7 districts) - Court ID: `arkansasctapp`

### Data Types Available
1. **Opinions** - Slip opinions with neutral citations
2. **Syllabi** - Weekly syllabi summarizing decisions
3. **Court Rules** - Administrative rules
4. **Administrative Orders** - Court administrative orders
5. **Oral Arguments** - Video archives via Granicus

## 2. Official Court Websites

### Main Sites
| Site | URL | Status |
|------|-----|--------|
| Main Judiciary Website | https://arcourts.gov/ | Verified |
| Opinions Database | https://opinions.arcourts.gov/ark/en/nav.do | Verified |
| Supreme Court Section | https://arcourts.gov/courts/supreme-court | Verified |
| Court of Appeals Section | https://arcourts.gov/courts/court-of-appeals | Verified |
| Case Search (OPAD) | https://caseinfo.arcourts.gov/opad | Verified |
| Oral Argument Videos | https://arkansas-sc.granicus.com/ | Verified |

## 3. Court Structure

### Supreme Court Justices (7 total)

| Justice | Position | Year Elected/Appointed | Bio Page |
|---------|----------|------------------------|----------|
| **Karen R. Baker** (Chief Justice) | Position 1 | 2024 | [Link](https://arcourts.gov/courts/supreme-court/justices/chief-justice-karen-r-baker-position-1) |
| Courtney Rae Hudson | Position 2 | 2024 | [Link](https://arcourts.gov/courts/supreme-court/justices/associate-justice-courtney-rae-hudson-position-2) |
| Cody Hiland | Position 3 | 2024 | [Link](https://arcourts.gov/courts/supreme-court/justices/associate-justice-cody-hiland-position-2) |
| Barbara Webb | Position 4 | 2020 | [Link](https://arcourts.gov/courts/supreme-court/justices/associate-justice-barbara-webb-position-4) |
| Shawn A. Womack | Position 5 | 2016 | [Link](https://arcourts.gov/courts/supreme-court/justices/associate-justice-shawn-a-womack-position-5) |
| Nicholas Bronni | Position 6 | 2024 | [Link](https://arcourts.gov/courts/supreme-court/justices/associate-justice-karen-r-baker-position-6) |
| Rhonda K. Wood | Position 7 | 2022 | [Link](https://arcourts.gov/courts/supreme-court/justices/justice-rhonda-wood-position-7) |

### Court of Appeals Judges (12 total)

| Judge | District | Position | Bio Page |
|-------|----------|----------|----------|
| Ray Abramson | District 1 | Position 1 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/Ray-Abramson) |
| Cindy Thyer | District 1 | Position 2 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/cindy-thyer) |
| Bart Virden | District 2 | Position 1 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/bart-virden) |
| Mike Murphy | District 2 | Position 2 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/Mike-Murphy) |
| Robert J. Gladwin | District 3 | Position 1 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/robert-j-gladwin) |
| Kenneth S. Hixson | District 3 | Position 2 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/kenneth-s-hixson) |
| Brandon Harrison | District 4 | Position 1 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/brandon-harrison) |
| Stephanie Potter Barrett | District 4 | Position 2 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/stephanie-barrett) |
| **Mark Klappenbach** (Chief Judge) | District 5 | - | [Link](https://arcourts.gov/courts/court-of-appeals/judges/Mark-Klappenbach) |
| Casey R. Tucker | District 6 | Position 1 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/rita-w-gruber) |
| Waymond M. Brown | District 7 | - | [Link](https://arcourts.gov/courts/court-of-appeals/judges/waymond-m-brown) |
| Wendy Scholtens Wood | District 6 | Position 2 | [Link](https://arcourts.gov/courts/court-of-appeals/judges/wendy-wood) |

## 4. Opinions Database (Lexum/Norma Platform)

### Base URL
`https://opinions.arcourts.gov/ark/`

### Navigation Options
| Navigation Type | Supreme Court URL | Court of Appeals URL |
|-----------------|-------------------|----------------------|
| By Date | `/supremecourt/en/nav_date.do` | `/courtofappeals/en/nav_date.do` |
| By Case Name | `/supremecourt/en/nav_alpha.do` | `/courtofappeals/en/nav_alpha.do` |
| By Neutral Citation | `/supremecourt/en/nav_neu.do` | `/courtofappeals/en/nav_neu.do` |
| By Report Citation | `/supremecourt/en/nav_re.do` | `/courtofappeals/en/nav_re.do` |
| By Term | `/nav_su.do` (combined) | - |

### URL Patterns

#### Opinion Item Pages
- Supreme Court: `https://opinions.arcourts.gov/ark/supremecourt/en/item/{id}/index.do`
- Court of Appeals: `https://opinions.arcourts.gov/ark/courtofappeals/en/item/{id}/index.do`

#### PDF Download
- Supreme Court: `https://opinions.arcourts.gov/ark/supremecourt/en/{id}/1/document.do`
- Court of Appeals: `https://opinions.arcourts.gov/ark/courtofappeals/en/{id}/1/document.do`

#### Year-Specific Navigation
- Supreme Court: `https://opinions.arcourts.gov/ark/supremecourt/en/{year}/nav_date.do`
- Court of Appeals: `https://opinions.arcourts.gov/ark/courtofappeals/en/{year}/nav_date.do`

#### Pagination
- Add `?page={n}` to any navigation URL (default shows 25 results per page)

### Advanced Search
- URL: `https://opinions.arcourts.gov/ark/en/a/s/index.do`
- Supports full-text search with syntax: `""`, `OR`, `AND`, `EXACT()`, `/p`, `/s`, `/n`

## 5. Citation Formats

### Neutral Citations (Official)
| Court | Format | Example |
|-------|--------|---------|
| Supreme Court | `{year} Ark. {number}` | 2026 Ark. 4 |
| Court of Appeals | `{year} Ark. App. {number}` | 2026 Ark. App. 40 |

**Note**: As of February 14, 2009, Arkansas became the first state court to designate the electronic version as the official version of its opinions.

### Case Number Formats (Docket Numbers)
| Type | Format | Example |
|------|--------|---------|
| Criminal | `CR-YY-###` | CR-24-603 |
| Civil | `CV-YY-###` | CV-25-319 |
| Civil (older) | `CV-YY-###` | CV-21-282 |

## 6. Opinion Types and Document Categories

### Document Types
| Type | Description | Precedential |
|------|-------------|--------------|
| Majority | Main opinion of the court | Yes |
| Majority, with Concurring | Opinion with concurrence | Yes |
| Majority, with Dissenting | Opinion with dissent | Yes |
| Syllabus | Weekly summary of decisions | Reference only |

### Court Rules and Orders
| Category | URL |
|----------|-----|
| Court Rules | `https://opinions.arcourts.gov/ark/cr/en/nav_date.do` |
| Administrative Orders | `https://opinions.arcourts.gov/ark/ao/en/nav_date.do` |

## 7. Publication Schedule

### Supreme Court
- **Decisions Released**: Thursdays at 10:00 AM during court term
- **Term**: First week of September to first week of July
- Justices also meet during summer to consider motions

### Court of Appeals
- **Decisions Released**: Wednesdays at 9:00 AM during court term
- **Term**: Mid-August to July 4 of the following year

## 8. RSS Feeds and Notifications

### Available RSS Feeds
| Feed | URL |
|------|-----|
| Supreme Court | `https://opinions.arcourts.gov/ark/supremecourt/en/rss.do` |
| Court of Appeals | `https://opinions.arcourts.gov/ark/courtofappeals/en/rss.do` |
| Court Rules | `https://opinions.arcourts.gov/ark/cr/en/rss.do` |
| Administrative Orders | `https://opinions.arcourts.gov/ark/ao/en/rss.do` |

### Mailing List
- URL: `https://opinions.arcourts.gov/ark/en/l.do`

## 9. Case Search System (OPAD)

### URL
`https://caseinfo.arcourts.gov/opad`

### Search Capabilities
- Search by participant name (First, Middle, Last)
- Search by organization or case description
- Advanced filters available

### Tips
- Navigation tips: https://www.arcourts.gov/administration/acap/navtips
- Safari users may need to allow pop-ups for document viewing

## 10. Oral Arguments

### Video Archive
- Platform: Granicus
- URL: `https://arkansas-sc.granicus.com/ViewPublisher.php?view_id=3`
- Archive page: `https://arcourts.gov/courts/supreme-court/oral-argument-videos`

### Supreme Court Schedule
- URL: `https://arcourts.gov/courts/supreme-court/schedule`
- Location: Justice Building, 625 Marshall Street, Little Rock, Arkansas
- Proceedings start at 10:00 AM
- Open to the general public

### Court of Appeals Schedule
- URL: `https://arcourts.gov/courts/court-of-appeals/schedule`

## 11. Historical Data

### Supreme Court Opinions
- Available from **1837 to present**
- Extensive historical archive

### Court of Appeals Opinions
- Available from **1979 to present**
- Court was established in 1979

## 12. Access Restrictions

### No Restrictions
- No login required for opinion search and download
- No date limitations
- No CAPTCHA observed
- PDF downloads available directly
- RSS feeds publicly accessible

### Notes
- Some embedded iframes in the opinions interface may have mixed content warnings
- Documents open in new windows (Safari pop-up blockers may interfere)

## 13. Technical Implementation Notes

### Platform
- Lexum Norma (https://lexum.com/en/norma/)
- Website last modified tracking available

### Key Technical Features
1. **Sequential Item IDs**: Opinions use sequential numeric IDs (e.g., 524102, 524103)
2. **Predictable URL Structure**: URLs follow consistent patterns
3. **RSS Feeds**: Available for automated monitoring
4. **Pagination**: Standard pagination with `?page=N` parameter
5. **Embedded iframes**: Opinions are displayed in iframes within the main site frame

### Challenges
1. **Iframe Structure**: Main content is loaded in iframes, requiring frame navigation
2. **No Direct API**: All data must be scraped from HTML pages
3. **Mixed Content Warnings**: Some Granicus content served over HTTP

## 14. Example Cases

### Supreme Court Example
- **Case**: JONATHAN ROLFE v. STATE OF ARKANSAS
- **Citation**: 2026 Ark. 4
- **Date**: 01/22/2026
- **Item ID**: 524102
- **Item URL**: `https://opinions.arcourts.gov/ark/supremecourt/en/item/524102/index.do`
- **PDF URL**: `https://opinions.arcourts.gov/ark/supremecourt/en/524102/1/document.do`
- **Type**: Supreme Court - Majority
- **Term**: 2026 Spring Term

### Court of Appeals Example
- **Case**: ALVIN EUGENE YARBERRY v. STATE OF ARKANSAS
- **Citation**: 2026 Ark. App. 40
- **Date**: 01/21/2026
- **Item ID**: 524094
- **Item URL**: `https://opinions.arcourts.gov/ark/courtofappeals/en/item/524094/index.do`
- **PDF URL**: `https://opinions.arcourts.gov/ark/courtofappeals/en/524094/1/document.do`
- **Type**: Court of Appeals - Majority
- **Term**: 2026 Spring Term

## 15. Recommended Scraping Strategy

### For Opinions
1. Use RSS feeds for new opinion monitoring
2. Parse opinion list pages by date for historical data
3. Extract item IDs from listing pages
4. Construct PDF download URLs from item IDs
5. Parse opinion metadata from item pages

### For Recent Additions
1. Monitor the main page `https://opinions.arcourts.gov/ark/en/nav.do` for "Recent Additions"
2. RSS feeds provide immediate notification of new opinions

### Scraper Structure
```
juriscraper/sd/state/arkansas/
├── __init__.py
├── arkansas.py           # Supreme Court opinions
├── arkansasctapp.py      # Court of Appeals opinions
└── RESEARCH.md           # This file
```

## 16. Contact Information

### Administrative Office of the Courts
- Address: 625 Marshall Street, Little Rock, AR 72201
- Phone: 501-682-9400

### Clerk of Courts (Supreme Court)
- Phone: 501-682-6849

### Court of Appeals
- Phone: 501-682-7460

### Court Information Systems Division
- Contact: Tim Holthoff
- Email: tim.holthoff@arcourts.gov
- Phone: 501-410-1919

## 17. Comparison to Other States

### Similar to Alabama
- Both have Supreme Court and Court of Appeals
- Both provide public access without login
- Both use neutral citations
- Both have video archives for oral arguments

### Differences from Alabama
- Arkansas uses Lexum/Norma platform vs Alabama's custom portal
- Arkansas has sequential item IDs vs Alabama's GUIDs
- Arkansas has much longer historical archive (1837 vs 2022)
- Arkansas designates electronic version as official
- Arkansas provides RSS feeds

### Similar to Alaska
- Both have unified case management systems
- Both provide PDF downloads without authentication
- Both have extensive historical data

### Differences from Alaska
- Arkansas uses third-party Lexum platform vs Alaska's custom CMS
- Arkansas has simpler URL structure (no encrypted parameters)
- Arkansas: 7 Supreme Court justices vs Alaska's 5
- Arkansas: 12 Court of Appeals judges vs Alaska's 4

## 18. References

- Main Judiciary Website: https://arcourts.gov/
- Opinions Database: https://opinions.arcourts.gov/ark/en/nav.do
- Case Search: https://caseinfo.arcourts.gov/opad
- Supreme Court: https://arcourts.gov/courts/supreme-court
- Court of Appeals: https://arcourts.gov/courts/court-of-appeals
- Oral Arguments: https://arcourts.gov/courts/supreme-court/oral-argument-videos
- Lexum Norma: https://lexum.com/en/norma/
