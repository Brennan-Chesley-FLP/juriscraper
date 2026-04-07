# California Appellate Courts Case Information Scraper Design

## Site Overview
- **Base URL**: https://appellatecases.courtinfo.ca.gov
- **Requires Playwright**: Yes -- bot protection (Imperva/Incapsula JS challenge blocks httpx/curl; returns 200 with obfuscated JS payload instead of HTML)
- **Framework**: ColdFusion (`.cfm` pages), server-rendered HTML behind JS challenge gate
- **Search types**: Case Number, Party Name, Attorney, Case Caption (no date-based search for cases)
- **Calendar**: Date-based search for oral arguments only

## Courts Covered

| `dist` Param | Display Name | Docket Prefix | Highest Observed | CourtListener ID |
|--------------|-------------|--------------|-----------------|-----------------|
| 0 | Supreme Court | S | S295928 | `cal` |
| 1 | 1st Appellate District | A | A175975 | `calctapp1d` |
| 2 | 2nd Appellate District | B | B343601 | `calctapp2d` |
| 3 | 3rd Appellate District | C | C102353 | `calctapp3d` |
| 41 | 4th Appellate District Div 1 | D | D087818 | `calctapp4d` |
| 42 | 4th Appellate District Div 2 | E | E088098 | `calctapp4d` |
| 43 | 4th Appellate District Div 3 | G | G066312 | `calctapp4d` |
| 5 | 5th Appellate District | F | F091244 | `calctapp5d` |
| 6 | 6th Appellate District | H | H053901 | `calctapp6d` |

Note: All three divisions of District 4 (D, E, G prefixes) map to a single
CourtListener court ID `calctapp4d`.

## Search Capabilities

1. **Case Number Search** (primary for scraping) -- Enter case number on the search page for the relevant `dist`. For unique matches, redirects directly to the case detail page. Works for appellate and trial court numbers.
2. **Party Name Search** -- Last name required (min 2 chars). Returns paginated results (25 per page). Useful for probing docket formats.
3. **Attorney Search** -- Similar to party search.
4. **Case Caption Search** -- Search by case title.
5. **Calendar Date Search** -- Oral arguments only; supports date range and division filter.

**Recommended approach**: Speculative entry by case number (one entry per court prefix). No date-based case search exists.

## Docket Number Formats

All courts use a single letter prefix + 6 sequential digits:

| Court | Pattern | Example |
|-------|---------|---------|
| Supreme Court | `S` + 6 digits | S295928 |
| 1st District | `A` + 6 digits | A175975 |
| 2nd District | `B` + 6 digits | B343601 |
| 3rd District | `C` + 6 digits | C102353 |
| 4th District Div 1 | `D` + 6 digits | D087818 |
| 4th District Div 2 | `E` + 6 digits | E088098 |
| 4th District Div 3 | `G` + 6 digits | G066312 |
| 5th District | `F` + 6 digits | F091244 |
| 6th District | `H` + 6 digits | H053901 |

Numbers are continuous (not year-partitioned) and appear to have small gaps. Numbers do not reset yearly.

## Data Available

The site has two distinct page layouts: **Supreme Court** and **Court of Appeal**.

### Case Summary -- Supreme Court (dist=0)
- Supreme Court Case Number (e.g., S280000)
- Supreme Court Opinion (PDF/DOCX download links when available)
- Court of Appeal Case(s) (district, division, case number with link)
- Case Caption
- Case Category (e.g., "Review - Criminal Appeal", "Review - Civil Appeal")
- Start Date (mm/dd/yyyy)
- Case Status (e.g., "case initiated", "closed; remittitur issued")
- Issues (detailed text describing legal questions)
- Disposition Date
- Case Citation
- Cross Referenced Cases

### Case Summary -- Courts of Appeal (dist=1-6, 41-43)
- Trial Court Case Number
- Court of Appeal Case Number
- Division (numeric, e.g., "4")
- Case Caption
- Case Type (e.g., "CV", "CR")
- Filing Date (mm/dd/yyyy)
- Completion Date
- Oral Argument Date/Time

### Docket Entries (both)
| Field | Type |
|-------|------|
| Date | mm/dd/yyyy |
| Description | str |
| Notes | str (may contain party name, attorney name) |

Also shows case caption, division, and case number at top.

### Briefs (both)
| Field | Type |
|-------|------|
| Brief type/description | str (e.g., "Opening brief on the merits filed") |
| Date Filed | mm/dd/yyyy |
| Party and Attorney | str (often empty) |
| Notes | str |

### Disposition -- Supreme Court
Table with Date and Description columns.
- Example: "08/28/2025 | Opinion: Affirmed in part/reversed in part"
- Note: "Only the following dispositions are displayed: Orders Denying Petitions, Orders Granting Rehearing and Opinions."
- Also shows Case Citation.

### Disposition -- Courts of Appeal
Structured key-value fields:
| Field | Type |
|-------|------|
| Description | str (e.g., "Voluntary dismissal") |
| Date | mm/dd/yyyy |
| Disposition Type | str (e.g., "Final") |
| Publication Status | str |
| Author | str |
| Participants | str |
| Case Citation | str |

### Parties and Attorneys (both)
Table with Party and Attorney columns:
- **Party cell**: Name, role (e.g., "Defendant and Appellant"), address (multi-line)
- **Attorney cell**: Name, firm/organization, address (multi-line, street + city + state + zip)

### Lower Court -- Supreme Court
| Field | Type |
|-------|------|
| Court of Appeal District/Division | str |
| Court of Appeal Case Number | str (with link) |
| Disposition | str (e.g., "Affirmed in full") |
| Disposition Date | mm/dd/yyyy |
| Trial Court | str |
| Trial Court Case Number | str |

### Trial Court -- Courts of Appeal
| Field | Type |
|-------|------|
| Trial Court Name | str |
| County | str |
| Trial Court Case Number | str |
| Trial Court Judge | str |
| Trial Court Judgment Date | mm/dd/yyyy |

### Scheduled Actions -- Courts of Appeal only
"Future Scheduled Actions" tab. Table with scheduled events (Date, Description). Not present on Supreme Court cases.

### Documents
- Supreme Court opinions available as PDF and DOCX: `https://www.courts.ca.gov/opinions/archive/{case_no}.PDF`
- No general document download tab; documents appear inline on summary page.

## Email Notifications

**Available** at `/email.cfm?dist={dist}` and `/email.cfm?dist={dist}&doc_no={case_no}`.

URL pattern: `https://appellatecases.courtinfo.ca.gov/email.cfm?dist={dist}&doc_no={doc_no}`

### Supreme Court notification event types:
- Answer/Reply to Petition for Review Filed
- Record on Appeal Filed (death penalty auto-appeal)
- Briefs Filed on the Merits
- Orders Filed Granting Review
- Disposition Filed
- Request for Modification of Opinion or Petition for Rehearing Filed
- Remittitur Issued
- Oral Argument set
- Notice of Forthcoming Opinion posted
- Time Extended for Court to Consider Petition for Review
- Opinion Available Online
- Extension of Time
- Response or Briefing Requested
- Response or Opposition Filed

Court of Appeal notifications likely have a similar but different set of events (not yet verified).

## Oral Arguments Calendar

**Available** at `/calendar.cfm?dist={dist}`.

### Search modes:
1. **By Case Number** -- Enter appellate or trial court case number
2. **By Date** -- Start date (required, mm/dd/yyyy), end date (optional), division filter (optional, 1-8 for Supreme Court)
3. **By Case Caption** -- Text search

### Fields:
- Date/time of scheduled oral argument
- Case number, case caption
- Division

External link: https://www.courts.ca.gov/2116.htm (published OA calendars)

## Bot Protection Notes

- **Imperva/Incapsula** JS challenge on all pages. `curl` returns HTTP 200 with an obfuscated JavaScript payload (~199KB) instead of page HTML.
- No hidden form fields observed in the search forms.
- `request_token` parameter required in case detail page URLs. Generated server-side during search session. Attempting to navigate directly to a case URL with `request_token=auth` (the placeholder in search result links) redirects to an error page. Must go through the search flow to get a valid token.
- `doc_id` is an internal numeric ID assigned per case; required in all tab URLs alongside `doc_no` (the case number).
- Pagination uses `start` parameter (e.g., `start=26` for page 2 of 25-per-page results).
- Tab URLs follow consistent pattern: `case/{page}.cfm?dist={dist}&doc_id={id}&doc_no={no}&request_token={token}`

## Scraper Architecture

### Entry Points

One speculative entry per court prefix (9 total):

| Entry Function | Type | Prefix | `dist` | Court ID |
|---------------|------|--------|--------|----------|
| `fetch_supreme_court_docket` | `SimpleSpeculation(295928, 100)` | S | 0 | `cal` |
| `fetch_dist1_docket` | `SimpleSpeculation(175975, 100)` | A | 1 | `calctapp1d` |
| `fetch_dist2_docket` | `SimpleSpeculation(343601, 100)` | B | 2 | `calctapp2d` |
| `fetch_dist3_docket` | `SimpleSpeculation(102353, 100)` | C | 3 | `calctapp3d` |
| `fetch_dist4d1_docket` | `SimpleSpeculation(87818, 100)` | D | 41 | `calctapp4d` |
| `fetch_dist4d2_docket` | `SimpleSpeculation(88098, 100)` | E | 42 | `calctapp4d` |
| `fetch_dist4d3_docket` | `SimpleSpeculation(66312, 100)` | G | 43 | `calctapp4d` |
| `fetch_dist5_docket` | `SimpleSpeculation(91244, 100)` | F | 5 | `calctapp5d` |
| `fetch_dist6_docket` | `SimpleSpeculation(53901, 100)` | H | 6 | `calctapp6d` |

Optional future entry point for oral arguments by date range via Calendar page.

### Step Functions

**Flow for each case:**
```
entry (search page) → parse_search_page (submit case number form)
  → parse_case_summary (extract summary, navigate to docket tab)
    → parse_docket (extract entries, navigate to briefs tab)
      → parse_briefs (extract briefs, navigate to disposition tab)
        → parse_disposition (extract disposition, navigate to parties tab)
          → parse_parties (extract parties/attorneys, navigate to trial court tab)
            → parse_trial_court (extract trial court info)
              → assemble_docket (yield ParsedData)
```

Supreme Court cases use a slightly different parsing path for the summary and
lower court tabs due to different field names.

### Models
- `CaAppDocketEntry` -- single docket entry (date, description, notes)
- `CaAppBrief` -- brief record (type, date_filed, party_attorney, notes)
- `CaAppDisposition` -- disposition info (varies by court type)
- `CaAppParty` -- party with role and address
- `CaAppAttorney` -- attorney with firm and address
- `CaAppTrialCourtInfo` -- trial court details (embedded in main docket)
- `CaAppLowerCourtInfo` -- lower court details for Supreme Court cases
- `CaAppDocket` -- main output model containing all nested data
