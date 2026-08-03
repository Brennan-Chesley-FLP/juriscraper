# Supreme Court of Georgia (pubdoc.gasupreme.us) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single court (`ga`). **JSON-only** scraper against the
> `pubdoc.gasupreme.gov/api` REST API — no HTML, so no `parsers/` package
> (§3.5; arkansas/nevada shape).
> Plain HTTP (`driver_requirements = []`), no auth/bot-protection. Model fields
> follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `date_*` date naming, `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: https://www.gasupreme.us/docket-search/ (the marketing site is
  still on `.us`; `www.gasupreme.gov/docket-search/` 404s)
- **Embedded app**: https://pubdoc.gasupreme.gov/ui/ (the public docket-search
  UI is rendered inside an `<iframe>` pointing at this domain; the old
  `pubdoc.gasupreme.us` 301s here)
- **REST API**: https://pubdoc.gasupreme.gov/api/ (plain JSON, no auth, no
  cookies, no CSRF tokens — the SPA at pubdoc just calls these endpoints
  directly)
- **Requires Playwright**: **No** — the entire scrape runs against the JSON
  API with httpx.
- **Coverage**: rolling 5-year window. As of 2026-08-03 the window starts
  mid-`S21` (that prefix returns only 11 cases; `S20` returns none, `S22`
  onward are complete at ~1,300/year). `S26` holds 1,823 cases.

### Endpoint migration (2026-08-03)

The API moved from its own host onto the SPA's origin under an `/api` prefix:

| Then | Now |
|------|-----|
| `https://sced-rest.gasupreme.us/public-docket/query` | `https://pubdoc.gasupreme.gov/api/public-docket/query` |
| `https://sced-rest.gasupreme.us/public-docket/case/{n}` | `https://pubdoc.gasupreme.gov/api/public-docket/case/{n}` |

`sced-rest.gasupreme.us` no longer resolves at all (it CNAMEs to a Barracuda
WaaS name that is NXDOMAIN), so there is no fallback to keep. Payload shapes
are byte-identical to the old host — same query grammar, same field names on
both the query rows and the case detail. The un-prefixed path on the new host
404s; `/api` is required. Access control is unchanged: `/api/openapi`,
`/api/search`, and friends still 401, while `/api/public-docket/query`,
`/api/public-docket/case/{n}`, and `/api/system-data/two-val-const` are public.

## Courts Covered

| Site ID | Display Name | CourtListener ID |
|---------|-------------|-----------------|
| (single court) | Supreme Court of Georgia | `ga` |

The Georgia Court of Appeals is a separate site and is not covered here, even
though the docket detail records contain `coaCaseNumber`-style cross-refs.

## Search Capabilities

The portal exposes six search modes in the UI combobox, all backed by a
single endpoint:
`GET /api/public-docket/query?queryFilter=<Field> <Op> <Value>`.

The Java enums backing the query language reveal a wider surface than the UI
exposes. Probing both `SearchParams` and `SearchOperations` (their names
leak through `Internal Server Error: No enum constant ...` messages) gave
the full grammar:

### Searchable fields (`SearchParams` enum)

| Field                  | UI label                                | Notes |
|------------------------|-----------------------------------------|-------|
| `CaseNumber`           | Search By Case Number                   | UI uses `STARTS_WITH` |
| `CaseStyle`            | Search By Case Style                    | UI uses `CONTAINS` |
| `Party`                | Search By Party Name(s)                 | UI uses `CONTAINS` |
| `LowerCourtCaseNumber` | Search By Lower Court Case Number       | UI uses `STARTS_WITH` |
| `CoaCaseNumber`        | Search By Court of Appeals Case Number  | UI uses `STARTS_WITH` |
| `Attorney`             | Search By Attorney                      | UI uses `CONTAINS` |
| `CaseType`             | (not exposed in UI)                     | Single letter, e.g. `EQUALS A` returns 1,606 direct-appeal cases across the window |

Fields confirmed **not** in the enum (each returned the
`No enum constant ... SearchParams.<x>` error): `DocketDate`, `FilingDate`,
`UpdateDate`, `UpdatedDate`, `LastModified`, `ModifiedDate`, `JudgmentDate`,
`Status`, `CaseStatus`, `County`, `Description`, plus the lowercase
variants. **There is no date-based search and no last-modified search of any
kind.**

### Operators (`SearchOperations` enum)

| Operator       | Notes |
|----------------|-------|
| `EQUALS`       | exact match |
| `NOT_EQUALS`   | accepted; useful with `CaseType` to subtract a category |
| `STARTS_WITH`  | prefix match |
| `CONTAINS`     | substring match |
| `GREATER_THAN` | lexicographic comparison; **the closest the API gets to a "since" filter** — `CaseNumber GREATER_THAN S26C1300` returns every case whose number sorts after that cursor |
| `LESS_THAN`    | lexicographic, mirror of the above |

Operators that are **not** in the enum: `EQ`, `NE`, `GT`, `LT`, `LIKE`,
`MATCHES`, `BETWEEN`, `BEFORE`, `AFTER`, `IN`, `ENDS_WITH`.

### Other query-language limitations

- **No compound expressions.** `CaseType EQUALS A AND CaseNumber STARTS_WITH S26`
  returns `[]` — the server silently treats the expression as a literal
  third operand and matches nothing rather than ANDing the predicates.
- **No sort/pagination/limit params.** `sort=…`, `orderBy=…`, `limit=…`,
  `size=…`, `_sort=…`, `since=…`, `modifiedSince=…` are all silently
  ignored — the server returns the full unfiltered result list every time.
- **No undocumented endpoints.** Every other path under
  `https://pubdoc.gasupreme.gov/api/` (`/`, `/public-docket`, `/openapi`,
  `/api-docs`, `/case`, `/list`, `/recent`, `/updated`, `/search`, …)
  returns HTTP 401 Unauthorized. Only `/api/public-docket/query`,
  `/api/public-docket/case/{N}`, and `/api/system-data/two-val-const` are
  public. (Re-confirmed on the new host 2026-08-03; the query grammar above
  was probed on the old one and is unchanged.)

### What the API can and can't do for "recent updates"

| Goal | Supported? | How |
|------|-----------|-----|
| Find newly **docketed** cases since the last run | Yes | `CaseNumber GREATER_THAN <last-max-case-number>` returns lex-ordered new docket numbers (works because numbers are strictly sequential within each `S{YY}{LETTER}` bucket and `S` < `T` etc.) |
| Find newly **updated** cases (new filings/orders/judgments on existing cases) | **No** | No `LastModified` / `UpdatedDate` field exists. The only way to see an update is to refetch the case detail JSON. A complete incremental design therefore re-pulls every still-active case (status not in `Remittitur`/`Judgment`). |
| Filter by docket date range | No | `DocketDate` is not a SearchParams enum value |
| Filter by case status | No | `CaseStatus` is not a SearchParams enum value |
| Sort or paginate | No | Sort/limit params are silently ignored; the prefix query is uncapped anyway and returns ~1,300 cases per year-prefix in one response |

### Bulk enumeration

A useful, undocumented behaviour: **`CaseNumber STARTS_WITH S` returns the
entire 5-year docket** (~7,000 records, ~1.3MB) in one response, with no
pagination or result cap observed. Per-year prefixes (`S25`, `S26`, …) work
the same way and return ~1,300 cases each.

**Recommended approach**: enumerate by year prefix. `dockets_in_year` issues
one prefix query per seeded year and fetches case detail per number — seed
all six window years (`S21`–`S26`) for a full sweep, or just the current one
to keep it fresh. A watermark (`CaseNumber GREATER_THAN …`) buys nothing over
re-running the current year, since it can only surface newly docketed cases
and every case detail has to be refetched anyway to see new filings.

## Docket Number Formats

Case numbers are always `S` + two-digit year + one letter (case type) + four
digit sequence, e.g. `S26A0125`. The "year" is the calendar-of-court year;
new years roll over around early August (the earliest 2026-prefix case in
the dataset is `S26A0001` docketed 2025-08-04).

Letters seen in the live data, with their meanings (per the portal landing
page):

| Letter | Meaning |
|--------|---------|
| A | Direct appeal of a superior/state/probate/juvenile court order |
| B | Petition to appoint a Special Master in disciplinary proceedings |
| C | Petition for a writ of certiorari to review a Court of Appeals decision |
| D | Discretionary application to appeal a superior/state-court order |
| E | Certificate of probable cause — death-penalty habeas |
| F | Family Law Pilot Project direct appeal (largely defunct after 2017) |
| G | Granted petition for a writ of certiorari |
| H | Certificate of probable cause — post-conviction habeas denial |
| I | Interlocutory application to appeal |
| J | Judicial Qualifications Commission matters (pre-charges) |
| M | Emergency stay motion (notice-of-appeal filed but case not yet docketed) |
| O | Petition filed without prior lower-court review |
| P | Automatic direct appeal of a capital case with the death sentence imposed |
| Q | Certified questions of law from a federal court |
| R | Interim appellate review — pre-trial death-penalty cases |
| T | Request for extension of time |
| U | Review of UPL advisory opinions |
| W | Matters in cases with a scheduled execution |
| X | Cross-appeal |
| Y | Attorney discipline (State Bar of Georgia) |
| Z | Appeal from JQC or Office of Bar Admissions |

Per-letter counts for the S25 year prefix as of 2026-05-02 (gives a sense of
relative volume): A=333, B=53, C=444, D=79, G=19, H=252, I=32, J=4, M=20,
O=59, Q=1, T=107, U=9, X=7, Y=63, Z=4. E, F, P, R, W did not occur in S25
but are in the published letter list and are still supported by the parser.

## Data Available

### Case Summary

`GET /api/public-docket/case/{caseNumber}` — returns one JSON object. 404 for
missing/expired-window cases. Top-level fields:

| Field | Type | Notes |
|-------|------|-------|
| `caseNumber` | string | e.g. `S26A0125` |
| `caseStyle` | string | full caption / case name |
| `caseType` | string | one-letter code matching the caseNumber |
| `caseStatus` | string | e.g. `Docketed`, `Remittitur`, `Judgment` |
| `description` | string | e.g. `"Criminal - Murder Life"`, `"Criminal - Certiorari"` |
| `docketDate` | ISO date | docketing date with the Supreme Court |
| `docketCalendar` | string | calendar period, e.g. `"December 2025"` |
| `calendarCase` | bool | whether oral argument is scheduled |
| `county` | string | county of origin |
| `lowerCourtCaseNumbers` | string | trial-court docket(s); free-form, may include multiple separated by `;` |

### Filings and Orders (`filingsAndOrders` array)

| Field | Type | Notes |
|-------|------|-------|
| `filingType` | string | e.g. `"APPELLANT - Brief of Appellant"` |
| `filingDateTime` | ISO datetime | timestamp |
| `orderType` | string | only present when this filing is also an order, e.g. `"Appellee extension request granted"` |
| `orderDate` | ISO date | only present alongside `orderType` |
| `docketedInError` | bool | flag for entries the clerk has marked erroneous |

There are **no PDFs / no document downloads** on this portal — only entry
descriptions. The landing page directs users to the Clerk's Office to
purchase copies of documents.

### Judgments (`judgments` array)

| Field | Type | Notes |
|-------|------|-------|
| `judgment` | string | disposition, e.g. `"Affirmed"`, `"Certiorari - Writ denied"` |
| `judgmentLine` | string | per-curiam line, e.g. `"All the Justices concur."` |
| `judgmentDate` | ISO date | date of disposition |

### Attorneys (`attorneys` array)

The portal calls this list "Attorneys", but it includes both attorneys and
self-represented parties (an entry's `partyType` is set to `Appellant` /
`Appellee` etc.). Fields:

| Field | Type |
|-------|------|
| `firstName`, `middleName`, `lastName`, `suffix`, `title` | string |
| `firm` | string (may also hold a GDC inmate id for pro-se appellants) |
| `streetAddress1`, `streetAddress2`, `city`, `state`, `zip` | string |
| `phone` | string |
| `partyType` | string |

There is no separate "parties" list — only this combined attorneys list,
which we split into one record per attorney/pro-se row.

## Email Notifications

Not available — the public portal does not expose any subscribe/notify UI.

## Oral Arguments Calendar

The court publishes oral argument calendars on the marketing site
(https://www.gasupreme.us/calendar-list/) and webcasts at `/watch/`. Those
are unrelated to the pubdoc API and are out of scope for this
scraper.

## Bot Protection Notes

None. The API is plain JSON over HTTPS with no cookies, tokens, or
referrer/origin enforcement observed. A direct `curl` from the command line
returns the same payload as the browser.

## Scraper Architecture

### Entry Points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_in_year(court_ids, year)` | `set[str]`, `int` (4-digit `2026` or 2-digit `26`) | Issues one `CaseNumber STARTS_WITH S{YY}` prefix query — the site's only bulk feed — and yields a detail request per case number. Seed once per year of the rolling window (`2021`–`2026` as of 2026-08) for a full sweep. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Direct lookup against `/api/public-docket/case/{docket_number}`; the only way to pick up **updates** to a case we already know, since the search API has no last-modified field |

`dockets_in_year` takes the year rather than deriving the window itself, so
the caller controls how far back a run reaches; years outside the API's
rolling window come back as an empty list, not an error. The `STARTS_WITH`
prefix is applied with the two-digit year; no per-letter loop is needed
because the year prefix already returns every letter. Note the numbering
year rolls over in early August, so `S26` spans Aug 2025–Jul 2026.

There is no incremental entry. `CaseNumber GREATER_THAN <watermark>` would
catch newly *docketed* cases, but not new filings/orders on existing ones
(no last-modified field exists), so re-running `dockets_in_year` for the
current year — which re-fetches each case's detail — subsumes it.

### Step Functions

Flow:

```
dockets_in_year ────▶ parse_search_results (3) ──┐
                                                 ├─▶ parse_case_detail (2) ──▶ ParsedData(GaScDocket)
docket_by_number ────────────────────────────────┘
```

- `parse_search_results` (priority 3) reads the JSON list returned by the
  prefix query and yields one detail request per `caseNumber`, deduped on the
  docket id.
- `parse_case_detail` (priority 2) reads the per-case JSON object, splits
  attorneys and filings into nested models, and yields a single `GaScDocket`.

Priorities descend by depth (§5); no downloads (text-only API), so nothing at
0–1.

### Deduplication keys (§6)

- `search:prefix:<S26>` — the per-year prefix query.
- `case_detail:<case_number>` — each case-detail fetch (dedups the same case
  surfaced by multiple prefix sweeps).

### Models

- `GaScDocket` — top-level docket
- `GaScDocketEntry` — one row of `filingsAndOrders`
- `GaScJudgment` — one row of `judgments`
- `GaScAttorney` — one row of `attorneys` (handles both attorneys and
  self-represented parties; `partyType` carries the role)

No `GaScDocument` model — the portal exposes no downloadable files.
