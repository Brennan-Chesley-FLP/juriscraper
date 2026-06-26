# Arizona Court of Appeals, Division Two (appeals2.az.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single court (`arizctapp`, Division Two). Plain-HTTP ColdFusion site with
> a plaintext, session-bound captcha: a search is a GET (seed session
> cookie + fresh captcha) → POST (search criteria + parsed captcha)
> handoff, with the HTTP driver carrying the session cookies between them.
> Runs plain HTTP (`driver_requirements = []`); only a handful of searches
> are ever in flight, so we don't force `STRICTLY_SERIAL` — but see the
> Captcha note below for when it would be needed. HTML extraction lives in
> the `parsers/` package (§9, `CaseDetailParser`); steps keep navigation
> (captcha parsing, the search POST, the per-case fan-out). Model fields
> follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not
> `court_id`), `date_*` date naming, `CleanString`/`HarmonizedCaseName`
> cleaning.

## Site Overview

- **Base URL**: `https://www.appeals2.az.gov/ODSPlus/caseInfo.cfm`
- **Backend**: Adobe ColdFusion (`.cfm` paths) behind Cloudflare edge caching.
- **Requires Playwright**: No — server-rendered HTML, no JS challenge.

ColdFusion sets `CFID`/`CFTOKEN` session cookies on the first request and
binds the captcha to the session, so the scraper must keep the same session
(cookie jar) for the GET-then-POST search flow — which the HTTP driver does
automatically.

Separate scraper from `arizona/apps_azcourts_gov/` because it runs on a
different host (`appeals2.az.gov` vs `apps.azcourts.gov`) and exposes
structured docket text rather than PDFs.

## Courts Covered

| Site name | CourtListener ID |
|-----------|------------------|
| Arizona Court of Appeals, Division Two | `arizctapp` |

`courts-db` represents both Court-of-Appeals divisions under the single
`arizctapp` ID. The `apps_azcourts_gov` scraper covers Division One under the
same ID; this scraper covers Division Two. Records from both coexist —
distinguished by the `2 CA-` prefix on their docket numbers (vs `1 CA-` for
Division One).

## Search Capabilities

Single search form at `caseInfo.cfm`, posts to `caseInfo2.cfm`. Filters used:

| Field | Type | Notes |
|-------|------|-------|
| `ActiveCase` | checkbox `Y` | only currently-active cases |
| `CaseYear` | select | 1990–current year |
| `searchverifycode` | int (4 digits) | required captcha — see below |

Other filters exist on the form (`CaseTypeCode`, `CaseNumber`, `FilingDate`,
`CaseTitle`, `AttorneyLastName`/`AttorneyFirstName`, `County`,
`trialJudgeID`, `TrialCourtCaseNumber`) but are not used by this scraper.
The empty-form submission is rejected ("choose at least one search
criterion").

### Captcha

A four-digit number rendered in plaintext on the search form:

```html
Enter <strong><font color="FF0000">7820</font></strong> in this field:
<input name="searchverifycode" ...>
```

Regenerated on every GET to `caseInfo.cfm`, stored in the ColdFusion session
under `CFID`/`CFTOKEN`. To pass: GET `caseInfo.cfm`, parse the four digits,
POST `caseInfo2.cfm` on the **same session** with `searchverifycode=<that
number>`. We run plain HTTP because only a few searches are ever in flight.
The latent risk: if two searches share one cookie jar, a second GET could
overwrite the captcha before the first POST lands. If that's ever observed
(captcha-rejection errors in `parse_search_results`), set
`driver_requirements = [DriverRequirement.STRICTLY_SERIAL]` so searches run
one at a time. The downside is that it also serializes the ~800 captcha-free
case-detail fetches, so it's left off until needed.

### Search caps

- `ActiveCase=Y` alone → ~800 cases, single response, no pagination.
- `CaseYear=<year>` alone → ~700-1000 cases for recent years, fewer for older.

No apparent per-search cap up to ~1000 results, and no pagination markers.

## Docket Number Format

Display: `2 CA-<TYPE> <YYYY>-<NNNN>`, e.g. `2 CA-CR 2024-0280`. The
case-detail page is keyed on a numeric `caseID` (e.g. `134401`), carried on
the search-result link:

```html
<a href="caseInfolast.cfm?caseID=134401" target="_blank">2 CA-CR 2024-0280</a>
```

`caseID` is sequential — recent cases observed in the high 134000s. The
case-detail page (`caseInfolast.cfm?caseID=<id>`) is **directly accessible
without cookies or session**, which is why `docket_by_internal_id` skips the
search/captcha flow.

## Data Available

The case-detail page renders a full register of actions in plain HTML tables.
`CaseDetailParser` extracts:

- **Header** (`<th class="thcurves">`): docket_number, case_name, department,
  county, cause_numbers, trial judge (→ `assigned_to_str`),
  `date_submitted`, `date_at_issue`, at_issue_number.
- **Party/Attorney Information**: one `AzCoa2Party` per party (name, role) +
  nested `AzCoa2Attorney` (name, firm, appointment).
- **Filings, Dues, and Continuances**: `AzCoa2Filing` rows (document_type,
  document_title, `date_due`, `date_filed`, attorney, category).
- **Calendar and Agenda Information**: `AzCoa2OralArgument` rows.
- **Decision Information**: `AzCoa2Decision` rows.
- **Mandate** / **MR/PR Outcome** scalars (folded onto `AzCoa2Docket`).
- **Proceedings**: `AzCoa2Proceeding` rows — chronological master log;
  description whitespace preserved verbatim.

No downloadable PDFs are linked from the case-detail page — every document is
text-only on this site.

## Out of Scope

- `OACalendar.cfm` (oral-argument calendar) and `recentdecisions.cfm` exist
  with their own captcha forms; decision metadata is already on the
  case-detail page, so neither is implemented.
- No email-notification / subscribe links observed.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_bulk(court_ids)` | — | POST `ActiveCase=Y`; the site's bulk feed of all currently-active cases. |
| `dockets_by_filing_date(court_ids, date_range)` | `DateRange` | POST `CaseYear=<year>` once per year covered by the range (server searches by filing year). |
| `docket_by_internal_id(court_id, internal_id)` | `str`, `int` | Direct GET of one case-detail page by its numeric `caseID`. |

For a full backfill, run `dockets_by_filing_date` over 1990 → current.

### Step functions and priorities (§5)

```
entry → submit_search_form (4) → parse_search_results (3) → parse_case_detail (2)
                                                          └→ (per caseID)
docket_by_internal_id ────────────────────────────────────→ parse_case_detail (2)
```

Priorities descend by depth so in-flight cases finish before new searches
start. No downloads (text-only site), so nothing at priority 0–1.

### Deduplication keys (§6)

- `search_seed:active` / `search_seed:year:<year>` — the session-seeding GET.
- `search_results:active` / `search_results:year:<year>` — the search POST.
- `case_detail:<case_id>` — each case-detail fetch (dedups the same case
  surfaced by both the active and year searches).

### Data types

`AzCoa2Docket` (main, → CL `Docket`) with nested `AzCoa2Party` (+
`AzCoa2Attorney`), `AzCoa2Filing`, `AzCoa2OralArgument`, `AzCoa2Decision`,
`AzCoa2Proceeding`. Mandate and MR/PR outcomes are scalar, folded onto the
docket.
