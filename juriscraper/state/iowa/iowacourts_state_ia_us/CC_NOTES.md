# Iowa Appellate Courts (iowacourts.state.ia.us) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts share one `YY-NNNN` number space (`iowa` Supreme, `iowactapp`
> Court of Appeals); `court` is derived per-docket from a `TRANSFERRED TO
> COURT OF APPEALS` event. **Requires Playwright** (`JS_EVAL` + `FF_ALIKE`):
> Akamai Bot Manager returns HTTP 200 with an empty body to non-browser
> clients. HTML extraction lives in the `parsers/` package (§9); steps keep
> navigation (the search POST, the per-case tab chain, final assembly).
> Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court`
> (not `court_id`), `docket_number` (not `docket_id`), `assigned_to_str` for
> the trial judge, `date_*` naming, `CleanString`/`HarmonizedCaseName`.

Scrapes appellate docket data from the Iowa Judicial Branch's "Iowa Courts
Online" application at iowacourts.state.ia.us/ESAWebApp.

## Site Overview

- **Base URL**: https://www.iowacourts.state.ia.us/ESAWebApp/SelectFrame
- **Search hub**: `/ESAWebApp/SelectAction`
- **Appellate Simple Search**: `/ESAWebApp/AppelSimpFrame` → `/ESAWebApp/ACaseSimple`
- **Appellate Advanced Search**: `/ESAWebApp/AppelAdvFrame` → `/ESAWebApp/ACaseAdvanced`
- **Search submit**: `POST /ESAWebApp/AViewSearchResultsAdv`
- **Case wrapper**: `POST /ESAWebApp/AIndexFrm` (frameset, sets active caseid)
- **Case tabs (GET, all `?caseid=YY-NNNN&screen=null`)**:
  - `/ESAWebApp/AViewCase` — Summary (case type, status, judges, trial court, cite)
  - `/ESAWebApp/AViewLongTitle` — Formal caption
  - `/ESAWebApp/AViewDocket` — Register of Actions
  - `/ESAWebApp/AViewIssues` — Coded issues (almost always empty for public users)
  - `/ESAWebApp/AViewParties` — Parties + attorneys with `/ESAWebApp/AViewAttorney?<id>` links
- **Requires Playwright**: **Yes** — Akamai Bot Manager fronts the site (mPulse
  RYDVS-SB99L-MTVJH-7E27H-ZETAM). `curl` returns HTTP 200 with an empty
  body. The actual page renders only inside a real browser context.

The site is a frameset-based 1990s-era application built on IBM WebSphere /
Microsoft FrontPage. There is no JSON API; all output is server-rendered HTML.

## Courts Covered

| Display Name | CourtListener ID | How Identified |
|--------------|------------------|----------------|
| Supreme Court of Iowa | `iowa` | Default for cases with no transfer event |
| Court of Appeals of Iowa | `iowactapp` | Cases with a `TRANSFERRED TO COURT OF APPEALS` docket entry |

All Iowa appellate cases are docketed at the Supreme Court first (single
unified docket numbering: `YY-NNNN`). The Supreme Court then either retains
the case or transfers it to the Court of Appeals via the `TRANSFERRED TO
COURT OF APPEALS` docket event. Final disposition occurs at whichever court
holds the case at the time of the opinion.

### Court determination heuristic

Iterate the docket entries (newest first):

1. If any entry's event text contains `TRANSFERRED TO COURT OF APPEALS` →
   `iowactapp`.
2. Otherwise → `iowa`.

(There is also `RETAINED BY SUPREME COURT` for occasional cases that come
back from the CoA, but the latest transfer event is decisive.)

## Search Capabilities

| Rank | Mode | URL | Result Cap | Notes |
|------|------|-----|------------|-------|
| 1 | Date range (advanced) | `AViewSearchResultsAdv` `searchtype=A` | 2000 rows | Filters on **any docket activity in the window**, not filing date — case may have been filed in a prior year. |
| 2 | Docket number lookup | `AViewSearchResultsAdv` `searchtype=D` or direct `AViewCase?caseid=…` | n/a | Used for speculative entry. |
| 3 | Caption / party search | `searchtype=C` and `searchtype=A` (party form) | 2000 rows | Useful only for ad-hoc lookup. |

**Recommended approach**: hybrid.

- **Incremental**: date-range advanced search, one day per request, parse
  the result table, and chain into the case detail tabs. The 2000-row cap
  is reached for windows of ~7 days statewide; a single day is comfortably
  under (~1 900 rows for ~170 distinct cases). The scraper splits date
  ranges day-by-day to stay safe.
- **Backfill**: speculative `YearlySpeculativeRange` entry that probes
  every `YY-NNNN` directly via `AViewCase`. Year + sequential.

### Advanced search request (date-range mode)

`POST /ESAWebApp/AViewSearchResultsAdv`,
`Content-Type: application/x-www-form-urlencoded`:

```
last=&first=&role=ALL
&and%2For=and
&last=&first=&role=ALL
&issues1=ALL&issuesAndOr=AND&issues2=ALL
&casetype=ALL&status=ALL&event=ALL
&fromDate=04%2F20%2F2026
&toDate=04%2F20%2F2026
&searchtype=A
&search=Search
```

Note the doubled `last`, `first`, `role` — the form has two party slots.
Both sides are required (empty values OK). The "AND/OR" join field is
literally `and/or` (URL-encoded `and%2For`). Date format is `MM/DD/YYYY`.

Response is HTML with a single results table. Each case occupies one row
for the docket number/caption/status plus an additional row per party
(roles, attorneys). The clickable docket number link uses
`href="javascript:mySubmit('YY-NNNN')"`, which sets the hidden `caseid`
field on `AdvForm` and POSTs to `/ESAWebApp/AIndexFrm`.

### Docket number formats

- **Format**: `YY-NNNN` (2-digit year, 4-digit zero-padded sequence).
- **Range observed (2025)**: `25-0001` to `25-2200+` (annual filings ≈ 2 000-2 400).
- **Range observed (2026, mid-year)**: `26-0001` to `26-0776` as of 2026-05-03.
- **Continuous within a year**: the sequence is shared across both Supreme
  Court and Court of Appeals — a single number space.
- **Some gaps exist** (rejected filings, sealed cases, withdrawn appeals).

For `YearlySpeculativeRange`, seed each year with `min=1`, `gap=20`,
`soft_max≈2400` (or current sequence ceiling for the in-progress year).

## Session State

The site uses **server-side session state** to track the "active case" for
case-detail tab fetches. The pattern:

1. The first call to `AViewCase?caseid=YY-NNNN` sets the session's active
   caseid AND returns the Summary tab.
2. Subsequent calls to `AViewLongTitle`, `AViewDocket`, `AViewIssues`,
   `AViewParties` ignore their own `caseid` query parameter and use the
   session value instead.
3. Calling `AViewCase?caseid=DIFFERENT` resets the active caseid.

**Implication for the scraper**: tabs must be fetched in a strict
serialized chain per case, with `AViewCase` always first. The kent driver
preserves cookies across a Request continuation chain and does not
interleave step responses for one chain with HTTP calls from another, so
this pattern is safe within a single chain.

## Bot Protection

- **Akamai Bot Manager / mPulse**. Sets `_abck`, `bm_sz`, `bm_sv` cookies
  on first navigation; subsequent requests need them or they return empty
  bodies.
- A real browser (Playwright) handles this automatically.
- No captcha, no hidden CSRF tokens — once the Akamai cookies are set,
  every form post and tab GET works with an empty user agent and no
  custom headers.

## Data Available

### Case Summary (`AViewCase`)

| Field | Source | Notes |
|-------|--------|-------|
| Short title | "Short Title:" header | E.g. `State v. Sholley-Gonzalez` |
| Docket No. | First data cell | `YY-NNNN` |
| Case Type | Second data cell | `CRIMINAL CASE`, `CIVIL CASE`, `JUVENILE CASE`, etc. |
| Status | Third data cell | `NOTICE OF APPEAL FILED`, `SUBMITTED`, `OPINION FILED`, `DISPOSED`, … |
| Trial Court Judge | Fourth data cell | Name (often blank for new filings) |
| Appellate Judges/Justices | Section | List of names or `"No Judges Listed"` |
| Trial Court Case ID | Section | E.g. `FECR391937` |
| Originating County | Section | County name (`POLK`, `LINN`, etc.) |
| Cite | Section | Reporter cite when available, else `"No Cite Listed"` |
| EDMS marker | Sentinel | Real cases have `<span ...>EDMS</span>`. Non-existent cases have `<!-- !EDMS -->` (used for soft-404 detection). |

### Long Title (`AViewLongTitle`)

Formal multi-line caption (party names with `Plaintiff-Appellee` /
`Defendant-Appellant` labels). Rendered in a `<font face="Courier New">`
block; whitespace-collapse to derive `case_name_full`. Many older cases
have an empty Long Title.

### Docket / Register of Actions (`AViewDocket`)

Each entry is one HTML row group:

| Column | Field | Notes |
|--------|-------|-------|
| Date of Filing | `date_filed` | `MM/DD/YYYY` |
| Date Served | `date_served` | Optional |
| Event | `event_type` | E.g. `NOTICE OF APPEAL (CERT)`, `ORDER: PETITION FOR CERTIORARI DENIED`, `OPINION: AFFIRMED`, `TRANSFERRED TO COURT OF APPEALS` |
| Filed By | `filed_by` | Party / clerk / judge name |
| Due Date | `due_date` | Optional |
| Comments | `notes` | Optional follow-on row prefixed `<i>Comments:</i>` |

Each `<tr>` is preceded by `<!-- Event ID #NNNNN-->` and followed by
`<!-- No available Documents: {…} -->` (when no public PDF) or one or
more `<a>` anchors driving the `dl_document` form.

### Issues (`AViewIssues`)

A list of AOC-coded issues for the case. **Almost always empty** for
public users; structured issue tagging appears to be an internal feature.

### Parties (`AViewParties`)

| Column | Field |
|--------|-------|
| Name | Linked text (`<a href="/ESAWebApp/AViewAttorney?<id>">…</a>`) |
| Role | E.g. `APPELLANT`, `APPELLEE`, `ATTORNEY FOR APPELLANT`, `PRO SE`, `ATTORNEY GENERAL` |
| Status | `ACTIVE`, `WITHDRAWN`, `INACTIVE` |

Both human parties and attorney organizations appear in the same table;
they are separable by role text.

### Documents

The site **does not publish document PDFs to the public**. Every event
row in the docket is annotated with `<!-- No available Documents: … -->`.
The download form `dl_document` exists but its handler `DownloadFiling`
requires a logged-in courthouse-terminal account. The
`SelectFrame` index page explicitly notes:

> Appellate case electronic document viewing available, at a public
> terminal at the courthouse, in the county where the appeal was filed.

Accordingly the scraper **does not emit a document model** at this time.

## Email Notifications

Not available without registration. The site has a `Register` button on
every page; once a registered user is logged in there are case
subscription endpoints, but they are not in scope for this public scraper.

## Oral Arguments Calendar

Iowa publishes oral argument schedules separately on the Judicial Branch's
public site (`www.iowacourts.gov/iowa-courts/oral-arguments-and-calendars`),
not through ESAWebApp. Out of scope for this scraper.

## Soft-404 Detection

Non-existent docket numbers return HTTP 200 with the Summary template
filled in but blank. Reliable signals:

- HTML comment `<!-- !EDMS -->` (vs. `EDMS` span on real cases)
- Text fragment `&quot;No Trial Court Cases Listed&quot;` is present, AND
- The Case Type cell is empty.

The scraper overrides `fails_successfully` to detect these and swallow
the speculative miss as a non-error.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_activity_date(court_ids, date_range)` | `DateRange` | Incremental scrape via the advanced search. The server filters on **any docket activity** in the window (not the filing date), hence `_by_activity_date`. Splits the window into one-day POSTs to stay below the 2000-row cap. |
| `dockets_by_number(docket_number)` | `YearlySpeculativeRange` | Backlog speculation, one probe per `YY-NNNN` straight to `AViewCase`. Speculative entries take **only** their speculative param (§4) — no `court_ids` arg; the per-docket court is derived at assemble time, so one entry covers both courts. |

(The old `get_dockets()` params-reading variant was dropped — entries are
seeded by the driver, never from `self._params`.)

### Step functions and priorities (§5)

```
dockets_by_activity_date → (per day POST) parse_search_results (6)
    └→ (per case) parse_case_summary (5) → parse_long_title (4)
          → parse_docket_entries (3) → parse_parties (2) → ParsedData
dockets_by_number ─────────────────────→ parse_case_summary (5) → … → ParsedData
```

Priorities descend by depth so in-flight cases finish their tab chain
before new searches start. The site publishes no public PDFs, so there
are no downloads and nothing at priority 0–1.

### Tab session state

`AViewCase` sets the session's active caseid and returns Summary; the
later tabs (`AViewLongTitle`/`AViewDocket`/`AViewParties`) read the session
value, so the tabs must run as a single serialized continuation chain with
`AViewCase` first. The driver preserves cookies across a continuation chain
and doesn't interleave one chain's responses with another's, so this holds.

### Deduplication keys (§6)

- search POST → `SkipDeduplicationCheck()` (one non-idempotent POST/day).
- `case_summary:<docket_number>` — the first tab fetch; dedups a case
  surfaced by both a search day and the speculative entry. The downstream
  tab GETs inherit the default hashed key (URL + caseid).

### Parsers (`parsers/`, §9)

- `SearchResultsParser` — unique `YY-NNNN` docket numbers (returns `list[str]`).
- `CaseSummaryParser` — Summary-tab header scalars (returns a dict merged
  into `accumulated_data`).
- `LongTitleParser` — formal caption (`case_name_full`).
- `DocketEntriesParser` — `JKentParser[IowaDocketEntry]`, one per event row.
- `PartiesParser` — `JKentParser[IowaParty]`, one per linked party row.

### Models

- `IowaDocket` — main output (→ CL `Docket`).
- `IowaDocketEntry` — one register-of-actions row (→ CL `DocketEntry`).
- `IowaParty` — party or attorney row (→ CL `Party`/`Attorney`).

There is intentionally no `IowaDocument` model; see "Documents" above.
