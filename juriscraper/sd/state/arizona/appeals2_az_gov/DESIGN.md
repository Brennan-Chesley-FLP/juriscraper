# Arizona Court of Appeals, Division Two (appeals2.az.gov) Scraper Design

## Site Overview

- **Base URL**: `https://www.appeals2.az.gov/ODSPlus/caseInfo.cfm`
- **Real backend**: ColdFusion app at the same host (the URL paths use
  `.cfm`).
- **Requires Playwright**: No — server-rendered HTML, no bot challenge.

The site fronts an Adobe ColdFusion app behind Cloudflare's edge caching.
There is no JavaScript challenge gate; `httpx` works. ColdFusion sets
`CFID`/`CFTOKEN` session cookies on the first request and binds the
captcha (see below) to the session, so the scraper must keep the same
HTTP client (with its cookie jar) for the GET-then-POST search flow.

This is a separate scraper from `arizona/apps_azcourts_gov/` because it
runs on a different host (`appeals2.az.gov` vs `apps.azcourts.gov`) and
exposes structured docket text rather than PDFs.

## Courts Covered

| Site name | CourtListener ID |
|-----------|------------------|
| Arizona Court of Appeals, Division Two | `arizctapp` |

`courts-db` represents both Court-of-Appeals divisions under the single
`arizctapp` ID. The `apps_azcourts_gov` scraper covers Division One under
the same ID; this scraper covers Division Two. Records from both can
coexist — they are distinguished by the `2 CA-` prefix on their docket
numbers (vs `1 CA-` for Division One).

## Search Capabilities

Single search form at `caseInfo.cfm`, posts to `caseInfo2.cfm`. Available
filters (any combination):

| Field | Type | Notes |
|-------|------|-------|
| `ActiveCase` | checkbox `Y` | "Only search for cases that are currently active" |
| `CaseTypeCode` | select | `CR`, `CV`, `SA`, `CC`, `HC`, `JV`, `IC`, `MH` |
| `CaseYear` | select | 1990–current year |
| `CaseNumber` | int (1-4 digits) | last component of the docket |
| `FilingDate` | text (`mm/dd/yyyy`) | exact match |
| `CaseTitle` | text (partial) | caption substring |
| `AttorneyLastName` / `AttorneyFirstName` | text (partial) | per-attorney name |
| `County` | select | trial-court county |
| `trialJudgeID` | select | trial-court judge ID |
| `TrialCourtCaseNumber` | text (partial) | trial-court docket |
| `searchverifycode` | int (4 digits) | required captcha — see below |

The empty-form submission is rejected with "Please go back and choose at
least one search criterion for which to display results."

### Captcha

A four-digit number rendered in plaintext on the search form:

```html
Enter <strong><font color="FF0000">7820</font></strong> in this field:
<input name="searchverifycode" ...>
```

The number is regenerated on every GET to `caseInfo.cfm`, stored in the
ColdFusion session under the `CFID`/`CFTOKEN` cookies. To pass the check
the scraper must:

1. GET `caseInfo.cfm` with no cookies (or a fresh client).
2. Parse the four-digit number from the response HTML.
3. POST `caseInfo2.cfm` on the **same HTTP client** (so cookies are
   reused) with `searchverifycode=<that number>`.

`httpx.Client` (kent's default) preserves cookies across requests
automatically, so no manual cookie management is needed.

### Search caps

Tested:

- `ActiveCase=Y` alone → ~800 cases, single response, no pagination.
- `CaseYear=2024` alone → ~900 cases, single response, no pagination.

There is no apparent per-search cap up to ~1000 results, and no
pagination markers in the HTML. Older years return fewer results.

### Recommended approach

Two entry points, as the user requested:

1. **`active_cases`** — POSTs `ActiveCase=Y`. Returns every currently
   active case across all years and types in a single response.
2. **`cases_by_year`** — takes a `year: int` parameter. POSTs
   `CaseYear=<year>`. Returns every case filed in that year regardless of
   status.

For a full backfill, run `cases_by_year` for each year 1990 → current.

## Docket Number Format

Display: `2 CA-<TYPE> <YYYY>-<NNNN>`, e.g. `2 CA-CR 2024-0280`.

The case detail page is keyed on a numeric `caseID` (e.g. `134401`)
rather than the display number. The link in search results carries it:

```html
<a href="caseInfolast.cfm?caseID=134401" target="_blank">2 CA-CR 2024-0280</a>
```

`caseID` is sequential — recent cases observed in the high 134000s.

## Data Available

The case detail page (`caseInfolast.cfm?caseID=<id>`) is **directly
accessible without cookies or session** and renders a full register of
actions in plain HTML tables. Sections (in order, demarcated by HTML
comments):

### Case header (top of page, in a `<th class="thcurves">`)

| Field | Source |
|-------|--------|
| `docket_number` | First line of the header (e.g. `2 CA-CR 2024-0280`) |
| `case_name` | Rest of the first line after the docket number |
| `department` | `<b>Department:</b> X` |
| `county` | `<b>County:</b> X` |
| `cause_numbers` | `<b>Cause Numbers:</b> X` (comma-separated) |
| `trial_judge` | Free text after the cause numbers |
| `submitted_date` | `<b>Submitted:</b> mm/dd/yyyy` |
| `at_issue_date` | `<b>At Issue Date:</b> mm/dd/yyyy` |
| `at_issue_number` | `<b>At Issue Number:</b> NNNN-NNNN` |

### Party/Attorney Information (`<!--begin party/attorney info -->`)

A 2-column table (Party / Attorney). Each row carries one party and one
or more attorneys for that party. Per-row fields:

- Party cell: party name + role (`Appellant` / `Appellee` / etc.)
- Attorney cell: attorney name(s); for each: firm and appointment kind
  (`Appointed`, `Retained`, `Pro Bono`, etc.).

Multiple attorneys per party appear as stacked blocks separated by
`<p></p>`.

### Filings, Dues, and Continuances (`<!--begin filings, dues, and continuances -->`)

6-column table:

| Column | Notes |
|--------|-------|
| `document_type` | "Opening Brief", "Notice of Appeal", "Trial Court Record", … |
| `due_date` | `mm/dd/yyyy` or empty |
| `document_title` | display title of the filing |
| `filing_date` | `mm/dd/yyyy` |
| `attorney` | filer's attorney name (or empty for clerk filings) |
| `category` | "Filing", "Due", "Continuance" |

### Calendar and Agenda Information (`<!--begin calendar and decisions info -->`)

Oral-argument metadata. 7-column table:

| Column |
|--------|
| `oa_request_due` |
| `oa_filed` |
| `oa_request_by` |
| `oa_request_result` |
| `oa_date` |
| `oa_time` |
| `oa_type` |

A single row per case (often empty for cases without scheduled OA).

### Decision Information

3-column table: `decision_type`, `decision_date`, `result_type`. One row
per decision (often empty for pending cases).

### Mandate (`<!--begin mandate info -->`)

2 scalar fields: `mandate_date`, `mandate_vacated_date`.

### MR/PR Outcome (`<!--begin MR info -->`)

4 scalar fields:
`mr_outcome`, `mr_outcome_date`, `pr_outcome`, `pr_outcome_date`.

(MR = Motion for Reconsideration; PR = Petition for Review.)

### Proceedings (`<!-- begin proceedings -->`)

3-column table: `proceeding_type` ("Record", "Briefs", "All Other"),
`proceeding_date`, `description`. The description cell can carry
multi-line judicial orders (formatted as preformatted text inside a
single `<td>`). This is the chronological master log.

## Documents

No downloadable PDFs are linked from the case detail page — every
document referenced in Filings or Proceedings is text-only on this site.
Briefs *are* sent to Thomson Reuters and Lexis brief-bank services per
the standing order in the proceedings text, but those services are
external paywalled aggregators.

## Email Notifications

Not available — no subscribe links observed.

## Oral Arguments Calendar

`OACalendar.cfm` exists and is structured (date sections + per-case
dept/time/type/county/judge cells). Out of scope for this initial
scraper; could be added later as a separate entry point yielding an
oral-argument data type.

## Decisions / Recent Opinions

`recentdecisions.cfm` has its own search form (similar captcha mechanic).
Not implemented in this scraper — the main case detail page already
surfaces decision metadata in the "Decision Information" table.

## Bot Protection Notes

- Plaintext captcha (`searchverifycode`) bound to the ColdFusion session.
- ColdFusion session cookies (`CFID`, `CFTOKEN`, `CFGLOBALS`).
- Cloudflare `__cf_bm` cookie (purely caching, no challenge).
- `Content-Security-Policy: frame-src 'self'; frame-ancestors 'self'`.

The captcha is the only friction; it is defeatable by parsing the digits
from the HTML.

## Scraper Architecture

### Entry points

| Entry | Param | Purpose |
|-------|-------|---------|
| `active_cases` | none | Search with `ActiveCase=Y`; returns all currently active cases. |
| `cases_by_year` | `YearSearch(year: int)` | Search with `CaseYear=<year>`; returns every case filed in that year. |
| `fetch_case` | `CaseId(case_id: int)` | Direct fetch of a single case detail by `caseID`. Useful for refetches. |

### Step functions

```
entry → submit_search_form → parse_search_results → parse_case_detail → ParsedData
                                                  └→ (per case)
```

- `submit_search_form`: parses the captcha number from the GET landing
  HTML, then POSTs `caseInfo2.cfm` with the search criteria carried in
  `accumulated_data["search_kind"]` and `accumulated_data.get("year")`.
- `parse_search_results`: extracts every `caseInfolast.cfm?caseID=<id>`
  link, yields a Request per case with `deduplication_key` set to the
  numeric ID.
- `parse_case_detail`: parses every section listed above and emits a
  fully-populated `AzCoa2Docket`.

### Data types

- `AzCoa2Docket` — main case record, with nested:
  - `parties: list[AzCoa2Party]`
  - `filings: list[AzCoa2Filing]`
  - `oral_arguments: list[AzCoa2OralArgument]`
  - `decisions: list[AzCoa2Decision]`
  - `proceedings: list[AzCoa2Proceeding]`
- `AzCoa2Party` — name + role + nested `attorneys: list[AzCoa2Attorney]`.
- `AzCoa2Attorney` — name + firm + appointment kind.
- `AzCoa2Filing` — one row from "Filings, Dues, and Continuances".
- `AzCoa2OralArgument` — one row from "Calendar and Agenda Information".
- `AzCoa2Decision` — one row from "Decision Information".
- `AzCoa2Proceeding` — one row from "Proceedings".

Mandate and MR/PR outcomes are scalar; folded into `AzCoa2Docket`.
