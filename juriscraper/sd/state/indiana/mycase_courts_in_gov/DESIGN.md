# Indiana MyCase (Appellate Courts) Scraper Design

## Site Overview

- **Base URL**: https://public.courts.in.gov/mycase/
- **Public app**: SPA at `https://public.courts.in.gov/mycase/#/vw/Search`
  (URL hash carries a base64-encoded JSON state; the SPA calls a plain JSON
  REST backend).
- **Backend stack**: ASP.NET MVC (`X-Powered-By: ASP.NET`,
  `X-AspNetMvc-Version: 5.2`).
- **Requires Playwright**: **No.** The JSON API is reachable directly with
  httpx — no CloudFlare, no JS challenge, no required cookies (verified with
  curl, status 200 + valid JSON for both search and case-detail endpoints).
- **Case management system**: Odyssey (Tyler Technologies). The same
  endpoints serve both Indiana trial courts and the appellate courts — this
  scraper restricts itself to the appellate `CourtItemID`s.

## Courts Covered

| Site `CourtItemID` | Display Name        | Case-number court letter | CourtListener ID |
|--------------------|---------------------|--------------------------|------------------|
| 95                 | Court of Appeals    | `A`                      | `indctapp`       |
| 96                 | Supreme Court       | `S`                      | `ind`            |
| 97                 | Tax Court           | `T`                      | `indtc`          |
| 94                 | All Appellate Courts (multiplexed search; not a real court) | — | — |

The "All Appellate Courts" item (94) is an aggregate — the scraper uses it
as a single-call shortcut for date-range searches that span all three
courts. Per-result `CourtCode` (`S`, `A`, `T`) is mapped back to the proper
CourtListener ID at parse time.

## Search Capabilities

The site exposes a single JSON search endpoint:

```
POST https://public.courts.in.gov/mycase/Search/SearchCases
Content-Type: application/json
X-Requested-With: XMLHttpRequest
```

Three search `Mode`s are supported in the request body: `ByCase`,
`ByParty`, `ByAttorney`. Date-range filtering is available on `ByParty`
when `Advanced: true` is set.

| Rank | Mode                                | Why                                                    |
|------|-------------------------------------|--------------------------------------------------------|
| 1    | `ByParty` + Advanced + date range   | Enables incremental scraping by `FileDate`             |
| 2    | `ByCase` exact docket number lookup | Enables targeted/speculative lookup of a known number  |
| 3    | `ByParty` + last name               | Useful for discovering docket-number formats           |
| 4    | `ByAttorney` / Bar number           | Not useful for bulk scraping                           |

**Recommended approach**: date-based primary discovery + by-case-number
lookup for arbitrary verified probes. There is no sequential-iteration use
case (see "Docket Number Formats" below — sequence numbers are
court-and-year scoped, *not* per-case-type, so `SpeculativeRange` style
iteration would have to fan out across every case-type prefix).

### Date-based search (primary)

Body shape:

```json
{
  "Mode": "ByParty",
  "Last": null, "First": null, "Middle": null, "Business": null,
  "DoBStart": null, "DoBEnd": null,
  "OANum": null, "BarNum": null, "SoundEx": false,
  "CaseNum": null, "CiteNum": null, "CrossRefNum": null,
  "CourtItemID": 95,
  "Categories": ["CR", "CV", "FAM", "PR"],
  "Limits": null,
  "Advanced": true,
  "ActiveFlag": "All",
  "FileStart": "04/01/2026",
  "FileEnd":   "04/30/2026",
  "CountyCode": null,
  "NewSearch": true,
  "CaptchaAnswer": null,
  "Skip": 0,
  "Take": 100,
  "Sort": "FileDate DESC"
}
```

Notes:
- `Categories` must be set; the SPA always sends the full set
  `["CR","CV","FAM","PR"]` for appellate searches. Sending an empty list
  returns no results.
- Date format is `MM/DD/YYYY`.
- `Advanced: true` is required for the date filter to be honoured.
- Pagination: `Skip` + `Take`; default Take is 20, 100 confirmed working.
- Result cap: **TotalResults caps at 1001**, and the UI shows "too many
  matches" for any query exceeding the cap. Court of Appeals can exceed
  this for ranges over ~3-4 months (avg ~286 cases/month). The scraper
  bisects the date range when `TotalResults > 1000`.

Observed monthly volumes (2026):
- Court of Appeals (`A`): ~286/month → bisect for >2-month windows.
- Supreme Court (`S`): ~35/month → safe up to a year.
- Tax Court (`T`): ~2-3/month → safe to query multi-year ranges.

### By-case-number lookup

```json
{ "Mode": "ByCase", "CaseNum": "26S-DI-00136", "CourtItemID": 92,
  "Categories": ["CR","CV","FAM","PR"], "Advanced": false, ... }
```

- Returns 1 result on a hit, 0 on a miss (`Results: null`).
- Works against the global CourtItemID 92 ("All Odyssey Courts"), which
  spans every court — convenient for arbitrary lookups without first
  knowing which appellate court issued the number.

### Captcha

The request body has a `CaptchaAnswer` field and the SPA loads a
`Captcha.tmpl.html` template. None of the Phase-2 probes triggered a
captcha challenge, so the trigger threshold is unknown but appears to be
high. The scraper should treat HTTP 403 / a JSON response with a
captcha-required marker as a `TransientException` rather than a hard
failure.

## Docket Number Formats

All three appellate courts share the same shape:

```
YY  C  -  TT  -  NNNNN
^^  ^     ^^     ^^^^^
|   |     |      |
|   |     |      sequence number (5 digits, zero-padded), reset yearly,
|   |     |      shared across all case types within a (court, year)
|   |     |
|   |     case-type prefix (2 letters)
|   |
|   court letter:  S = Supreme, A = Court of Appeals, T = Tax
|
two-digit year (year of filing)
```

Examples:
- `26S-DI-00136` — Supreme Court, Attorney Discipline, 2026 case #136
- `26A-CR-00794` — Court of Appeals, Direct Appeal (criminal), 2026 case #794
- `26T-TA-00009` — Tax Court, Tax Appeal, 2026 case #9
- `25A-CR-00001` — Court of Appeals 2025 case #1

Observed case-type prefixes (one-month sample, January 2026 onward):

| Court | Prefixes seen                                                                                                          |
|-------|-------------------------------------------------------------------------------------------------------------------------|
| `S`   | `OR` `DI` `PL` `CT` `CR` `JD` `EX` `LW` `PC` `MH`                                                                       |
| `A`   | `CR` `JT` `CT` `EX` `DC` `PL` `JP` `PC` `EV` `MI` `EU` `SC` `JC` `MH` `GU` `ES` `AD` `DN` `EM` `SP` `JV` `MF` `CC` `RA` `DR` `CB` `XP` `TR` `GV` `CE` `IF` `OV` `TP` |
| `T`   | `TA`                                                                                                                    |

`CR` = direct criminal appeal, `JT` = juvenile termination, `DI` =
attorney discipline, `OR` = original action, `TA` = tax appeal, etc.
The site doesn't expose a list of valid prefixes — they're implied by the
case-type list in the data. Because the 5-digit sequence is *shared across
all case types within a court+year*, sequential speculation by case-type
prefix would have huge gaps. Use date-based discovery for bulk and
by-number lookup for verification.

The site also accepts plain trial-court Odyssey case numbers (e.g.
`48C04-2406-F4-001929`) in `ByCase`, but those resolve to non-appellate
records and are out of scope for this scraper.

## Data Available

### Search-result row (lightweight)

| Field             | Type / Notes                                                  |
|-------------------|---------------------------------------------------------------|
| `CaseID`          | int (internal id; not persistent across searches)             |
| `CaseToken`       | str (single-use token used to fetch CaseSummary; ~5 min TTL?) |
| `CaseNumber`      | str (the public docket number, e.g. `26A-CR-00794`)           |
| `CourtCode`       | `"S  "`, `"A  "`, or `"T  "` (with trailing spaces)           |
| `Court`           | "Supreme Court" / "Court of Appeals" / "Tax Court"            |
| `FileDate`        | `MM/DD/YYYY`                                                  |
| `CaseStatus`      | "Pending", "Closed", "Transfer Granted", "Transfer Denied", … |
| `CaseStatusDate`  | `MM/DD/YYYY`                                                  |
| `CaseType`        | "CR - Direct Appeals (Non Capital, Non-LWOP)" etc.            |
| `CaseSubType`     | "Sentence Only", "Murder", "Tort-Negligence", … (nullable)    |
| `Style`           | Case caption                                                  |
| `IsActive`        | bool                                                          |
| `IsPublic`        | bool                                                          |
| `Parties`         | str (comma-joined preview)                                    |
| `Attorneys`       | str (comma-joined preview)                                    |

### Case detail (CaseSummary endpoint)

```
GET https://public.courts.in.gov/mycase/Case/CaseSummary?SRCT=&CaseToken={CaseToken}
X-Requested-With: XMLHttpRequest
```

Returns the full case as JSON. **CaseToken is short-lived** — fetch the
detail in the same scrape pass as the search; do not store and reuse.

Top-level fields:

| Field                         | Type                                              |
|-------------------------------|---------------------------------------------------|
| `InvalidToken`                | bool — `true` after the token expires             |
| `CaseNotFound`                | bool                                              |
| `AccessDenied`                | bool                                              |
| `CaseKey`                     | str (numeric internal id, stable)                 |
| `CaseCategoryKey`             | "CR" / "CV" / …                                   |
| `CaseCategoryGroup`           | "Civil" / "Criminal" / "Family" / "Probate"       |
| `CaseNumber`                  | str                                               |
| `Court`, `CourtCode`          | str                                               |
| `IsAppellateCourt`            | bool                                              |
| `FileDate`, `CaseStatus`, `CaseStatusDate` | `MM/DD/YYYY` / str                   |
| `CaseType`, `CaseTypeCode`, `CaseSubType` | str                                    |
| `Style`                       | str (case caption)                                |
| `IsActive`                    | "active" / "closed"                               |
| `IsPublic`                    | bool                                              |
| `AppearByDate`                | str / null                                        |
| `Flags`                       | list / null                                       |
| `Charges`, `Bonds`            | typically null for appellate                      |
| `Events`                      | list (chronological docket — see below)           |
| `Parties`                     | list (parties + attorneys — see below)            |
| `CrossRefs`                   | list (e.g. trial-court cause numbers)             |
| `Related`                     | list (e.g. lower trial-court case)                |

#### Event (one docket entry)

| Field                | Notes                                                            |
|----------------------|------------------------------------------------------------------|
| `EventKey`           | str                                                              |
| `EventType`          | short code: `ANOA`, `ABRIEF`, `AISSP`, `APTRF`, `ADPTRF`, …      |
| `BaseEventTypeKey`   | "C" / "MOT" / "ORD" / "OTHER" coarse bucket                      |
| `EventDate`          | `MM/DD/YYYY`                                                     |
| `Description`        | "Notice of Appeal Filed", "Brief - Appellant", "Opinion Issued", "Petition to Transfer", "Order Denying Petition to Transfer", "Memorandum Decision", … |
| `Judge`              | "Rush, Loretta H." or null                                       |
| `IsDocketable`       | bool                                                             |
| `EventDocuments`     | list of `{DocumentID, Name, EffectiveDate, PageCount, Filename, Ext, CanDown, DownUrl}` |
| `CaseEvent.Comment`  | freeform text (often the order's holding)                        |
| `CaseEvent.Date2`, `Date2Label` | secondary date with its label ("File Stamp" etc.)     |
| `CaseEvent.Parties`  | list of `{PartyLabel, Name}` (e.g. Attorney, Serve)              |
| `DispEvent`, `HearingEvent`, `JEvent`, `SEvent`, `VEvent`, `AEvent` | typed event extensions; null on most appellate rows |

Notable appellate `EventType` codes seen:
- `ANOA` Notice of Appeal Filed
- `ABRIEF` Brief - Appellant (carries PDF documents)
- `ABRIEFA` Brief - Appellee (carries PDF documents)
- `AISSP` Opinion Issued (carries the opinion PDF)
- `AOPCER` Opinion Certified
- `APTRF` Petition to Transfer
- `ADPTRF` Order Denying Petition to Transfer
- `AAPP` Appendix Filed
- `AMAIL` Document Transmitted (no doc)
- `ANCR` Notice of Completion of Clerk's Record
- `ANCT` Notice of Completion of Transcript
- `AFULLB` Case Fully Briefed
- `ATMAPP` Transmitted to Court of Appeals
- `ATRSUP` Transmitted on Transfer (Supreme Court)
- `ANRT` Notice Regarding Transfer
- `ANOTE` Note (no doc)
- `ARECEI` Received Document

The scraper does not enumerate this set — it captures `EventType` and
`Description` verbatim and lets downstream consumers classify.

#### Party

| Field             | Notes                                                       |
|-------------------|-------------------------------------------------------------|
| `Name`            | "Smith, Jason Michael" or "Disciplinary Commission"         |
| `NameFMLS`        | "Jason M. Smith" (formatted)                                |
| `BaseConnKey`     | "PL" / "DF"                                                 |
| `ExtConnCode`     | "PET" / "RES" / "APE" / "APR"                               |
| `ExtConnCodeDesc` | "Petitioner" / "Respondent" / "Appellant" / "Appellee"      |
| `Address`         | object: `{Line1, Line2, City, State, Zip, Zip4}` or masked  |
| `Attorneys`       | list (see below); empty for pro se                          |

#### Attorney (per-party)

| Field         | Notes                                            |
|---------------|--------------------------------------------------|
| `Name`        | "Mark Robert Conner"                             |
| `BarNumber`   | "#2553049" (with hash sign in payload)           |
| `Lead`        | bool                                             |
| `Label`       | "#2553049, Lead, Retained" / null                |
| `WorkPhone`   | str / null                                       |
| `Address`     | object or null                                   |

#### CrossRefs / Related

`CrossRefs` carries trial-court cause numbers (e.g. county Odyssey
identifiers like `48C042406F41929`). `Related` carries the lower trial
court case linked by Odyssey (`48C04-2406-F4-001929` plus the internal
`RelCaseKey`). Both are useful for cross-referencing the appellate case to
its underlying trial-court docket — captured in the model as
`trial_court_case_number` and `trial_court_internal_key` when present.

### Documents

`EventDocuments[].DownUrl` is a relative path:

```
/Case/Document/?token={signed_token}
```

It must be combined with the host (`https://public.courts.in.gov`) before
fetching. Tokens are signed and short-lived; fetch in the same scrape
pass. Files are PDFs (`Ext: "PDF"`) but `CanDown` is reported as `false`
in the JSON even when the document is in fact downloadable — ignore that
field and try the URL.

## Email Notifications

Not present on the case-summary page; the site's "Subscribe to RSS or
Email" footer link points at the static newsroom feeds, not per-case
alerts. Only signed-in users get docket alerts via "My Cases", which
requires authentication and is out of scope.

## Oral Arguments Calendar

The MyCase site does *not* expose an oral-arguments calendar. The Indiana
courts publish argument calendars at separate URLs (e.g.
`https://www.in.gov/courts/appeals/oral-arguments/`) that are HTML
schedules, not JSON. Out of scope for this scraper — a future scraper
would target those pages with a separate `OralArgument` model.

## Bot Protection Notes

- No CloudFlare / Akamai / hCaptcha / reCAPTCHA on the API path.
- No required cookies or session tokens for the search and case-detail
  endpoints (verified via curl).
- Required request headers: `Content-Type: application/json` (POST),
  `X-Requested-With: XMLHttpRequest` (recommended; without it, some MVC
  responses redirect to `/portal/`).
- The search body has a `CaptchaAnswer` field that is always sent as
  `null` from the SPA. The captcha trigger threshold appears to be high;
  treat captcha responses as transient.
- A reasonable rate limit (1–2 req/s) is sufficient.

## Scraper Architecture

### Entry Points

| Entry                                                | Param                          | Purpose                                                  |
|------------------------------------------------------|--------------------------------|----------------------------------------------------------|
| `get_supreme_dockets_by_date(date_range)`            | `DateRange`                    | Indiana Supreme Court (CourtItemID 96)                   |
| `get_court_of_appeals_dockets_by_date(date_range)`   | `DateRange`                    | Indiana Court of Appeals (CourtItemID 95)                |
| `get_tax_court_dockets_by_date(date_range)`          | `DateRange`                    | Indiana Tax Court (CourtItemID 97)                       |
| `fetch_docket_by_number(case_number)`                | `case_number: str`             | Speculative / verified single-case lookup by docket no.  |

The "all appellate" CourtItemID 94 isn't given its own entry — running
all three court-specific entries gives the same coverage with stable
court attribution.

### Step Functions

```
entry → search_appellate_dockets   (POST /Search/SearchCases)
       ↓ for each result hit       (and bisect or paginate as needed)
       fetch_case_detail           (GET /Case/CaseSummary?CaseToken=…)
       ↓ for each EventDocument
       download_document           (archive=True; GET /Case/Document/?token=…)
       ↓
       ParsedData(InDocket | InDocument)
```

Pagination: increment `Skip` until `Skip + Take >= TotalResults`. For
`TotalResults > 1000` (the cap), the scraper bisects the date range and
re-issues two queries.

### Models

- `InAttorney` — attorney representing a party
- `InParty` — case party with role + nested attorneys
- `InAddress` — addresses on parties / attorneys
- `InEventDocument` — manifest entry for a docket entry's PDF
- `InDocketEntry` — one chronological docket entry
- `InDocument` — separately-emitted record per archived PDF (with
  `local_path`)
- `InDocket` — the main per-case record carrying parties, entries, the
  document manifest, trial-court cross-references, source URLs

The court attribution (`court_id`) on `InDocket` is one of `ind`,
`indctapp`, `indtc` — derived from the per-result `CourtCode` letter.
