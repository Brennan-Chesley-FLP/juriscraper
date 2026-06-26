# California Appellate Courts Case Information — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single speculative entry `dockets_by_number(docket_number: CaCourtRange)`
> covers all nine courts/divisions. The target court can't be a separate
> `court_ids` argument — the driver dispatches a speculative entry with only
> its speculative param (see §4 "Multi-court speculative entries") — so it
> rides inside the param: `CaCourtRange` (a shared
> [`CourtRange`](../../../../state/common/params.py)) carries the
> CourtListener `court_id` and translates it to the site case-number prefix
> via `COURT_CONFIG`. Seed once per court (`SEED_HINTS` lists each
> `highest_observed`). Court ids match the classic juriscraper opinion
> scrapers — including a distinct id per Fourth-District division
> (`calctapp_4th_div1/2/3`) — so every prefix maps 1:1 to a court id. HTML
> extraction lives in the `parsers/` package (§9); steps keep navigation
> (tab-URL building, multi-result fan-out, archive requests, transient
> detection).

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
| 1 | 1st Appellate District | A | A175975 | `calctapp_1st` |
| 2 | 2nd Appellate District | B | B343601 | `calctapp_2nd` |
| 3 | 3rd Appellate District | C | C102353 | `calctapp_3rd` |
| 41 | 4th Appellate District Div 1 | D | D087818 | `calctapp_4th_div1` |
| 42 | 4th Appellate District Div 2 | E | E088098 | `calctapp_4th_div2` |
| 43 | 4th Appellate District Div 3 | G | G066312 | `calctapp_4th_div3` |
| 5 | 5th Appellate District | F | F091244 | `calctapp_5th` |
| 6 | 6th Appellate District | H | H053901 | `calctapp_6th` |

Note: court ids match the classic juriscraper opinion scrapers
(`juriscraper/opinions/.../state/calctapp_*`), which give each Fourth-District
division its own id — so every site case-number prefix maps 1:1 to a
CourtListener court.

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

One speculative entry, `dockets_by_number(docket_number: CaCourtRange)`,
probes `{prefix}{n:06d}` and the driver seeds/advances the range. Seed it
once per court (each seed gets its own speculation state); `CaCourtRange`
carries the CourtListener `court_id` and maps it to the prefix, and
`SEED_HINTS` in `scraper.py` lists each `highest_observed`
(largest_observed_gap was 100 for every court, 2026-04-03):

| Prefix | `dist` | Court ID | highest_observed |
|--------|--------|----------|------------------|
| S | 0 | `cal` | 295928 |
| A | 1 | `calctapp_1st` | 175975 |
| B | 2 | `calctapp_2nd` | 343601 |
| C | 3 | `calctapp_3rd` | 102353 |
| D | 41 | `calctapp_4th_div1` | 87818 |
| E | 42 | `calctapp_4th_div2` | 88098 |
| G | 43 | `calctapp_4th_div3` | 66312 |
| F | 5 | `calctapp_5th` | 91244 |
| H | 6 | `calctapp_6th` | 53901 |

Example seed: `{"dockets_by_number": {"docket_number": {"court_id": "cal",
"min": 295928, "soft_max": 295928, "gap": 100}}}`.

Optional future entry point for oral arguments by date range via Calendar page.

### Step Functions

Each entry returns a single search Request; the site redirects to the case
detail page. Step priorities descend by depth (downloads at 1):

```
entry → parse_case_summary  (7)  CaseSummaryParser; not-found → CaAppCaseUnavailable;
   │                              multi-result → fan out; opinion files → archive (1)
   ├→ parse_docket          (6)  DocketEntriesParser
   ├→ parse_briefs          (5)  BriefsParser
   ├→ parse_disposition     (4)  DispositionParser (+ SC citation promotion)
   ├→ parse_parties         (3)  PartiesParser
   └→ parse_trial_court     (2)  TrialCourtParser → _assemble_docket → ParsedData
```

`is_supreme` (set in the entry from the `S` prefix) is threaded down
`accumulated_data` and selects the SC vs CoA branch in the summary,
disposition, and trial-court parsers. Dates are parsed to `date` objects in
the parsers and survive `accumulated_data` JSON round-trips as ISO strings,
re-parsed at confirm.

### Parsers (`parsers/`)
- `CaseSummaryParser(is_supreme)` — summary `<dl>`, opinion links, subscriptions
- `DocketEntriesParser` — Register of Actions rows
- `BriefsParser` — brief rows
- `DispositionParser(is_supreme)` — SC table vs CoA key-value; `extract_case_citation`
- `PartiesParser` — party + attorney cells
- `TrialCourtParser(is_supreme)` — CoA trial court vs SC lower court

### Models (aligned to [`../../CL_MODELS.md`](../../CL_MODELS.md))
- `CaAppDocket` — main output (`docket_number`, `court`, `case_name`, `date_filed`,
  `date_terminated`, `date_argued`, …); maps to CL `Docket`
- `CaAppDocketEntry` — `DocketEntry` (date_filed, description, notes)
- `CaAppBrief` — brief record (type, date_filed, party_attorney, notes)
- `CaAppDisposition` — disposition info (varies by court type)
- `CaAppParty` / `CaAppAttorney` — `Party`/`PartyType` + `Attorney`
- `CaAppTrialCourtInfo` — CoA trial court → `OriginatingCourtInformation`
- `CaAppLowerCourtInfo` / `CaAppCoaCaseLink` — SC lower court block
- `CaAppOpinionFile` — archived opinion file → `RECAPDocument`
- `CaAppCaseUnavailable` — yielded for "Case Not Found" probes
