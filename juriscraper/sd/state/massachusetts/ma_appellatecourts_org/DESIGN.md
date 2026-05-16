# Massachusetts Appellate Courts Scraper Design

## Site Overview

- **Base URL**: https://www.ma-appellatecourts.org
- **Vendor**: RSI (River Software Inc) "Public Access" platform — Laravel
  backend (CSRF token field is `_token`).
- **Requires Playwright**: **Yes** — the site is fronted by Cloudflare's
  managed challenge. Plain `curl` returns HTTP 403 with a "Just a moment..."
  page; only after the JS challenge runs do subsequent requests succeed.
- **Bot protection**: Cloudflare managed challenge + a per-form Laravel CSRF
  token (`<input name="_token" ...>`) that must be POSTed back with each
  search. The token sits inside the search form on the GET render.

## Courts Covered

The site covers the entire Massachusetts appellate system — two courts,
seven case-type categories.

| Site `doc_doctp` | Display Name (per home form) | CourtListener ID | Notes |
|------------------|------------------------------|------------------|-------|
| `fc` | SJC Full Court Cases | `mass` | Court-of-last-resort merits docket |
| `sj` | SJC Single Justice Cases | `mass` | Single-justice motions |
| `oe` | SJC Original Entry Cases | `mass` | Original-jurisdiction cases (judicial discipline, bar matters, etc.) |
| `ar` | SJC DAR and FAR Applications | `mass` | Direct & Further Appellate Review applications |
| `bd` | SJC Bar Docket Cases | `mass` | Attorney discipline / bar admission |
| `ac` | Appeals Court Panel Cases | `massappct` | Intermediate appellate merits docket |
| `aj` | Appeals Court Single Justice Cases | `massappct` | Single-justice motions in the Appeals Court |

The Massachusetts Supreme Judicial Court (`mass`) and Appeals Court
(`massappct`) are the only two courts represented. All seven case-type
categories share a single search interface, distinguished only by
docket-number prefix and the `doc_doctp` form selector.

## Search Capabilities

| Rank | Mode | Available? | Notes |
|------|------|------------|-------|
| 1 | Date-based search | **No** | The advanced party form only filters by *Year Filed* (calendar year), never a date range. |
| 2 | Case number search | **Yes** | `GET /docket/{docket_id}` resolves directly to the case docket page. The docket number search form (`POST /docket`) just performs that redirect server-side. |
| 3 | Party name search | Yes | `POST /party` with `par_lname` (required) + optional `par_fname`, year, status, category, type. Paginates at `?page=N`. |
| 4 | Attorney / Lower-court / Lower-court-judge search | Yes | Auxiliary; not used for primary harvesting. |

**Recommended approach**: **speculative case-number probing**, one entry
point per (court, case-type) combination. Direct case-detail GETs are the
cheapest, most uniform way to enumerate the entire site, since every case
is reachable at `/docket/{docket_id}` regardless of how it was searched.

The party-name search is unsuitable as a primary entry point (it only
takes a Last Name and caps results at three pages of ~25 hits per query)
but is very useful for *discovering* the current high-water-mark of each
docket-number sequence during development.

There is **no oral-argument search by date**: the calendar pages
(`/calendar/{fc,sj,ac,aj}`) only show the *current month* and have no
month picker. They are useful as an additional surface for discovery but
do not function as a date-driven entry point.

## Docket Number Formats

Each case-type category has its own number format. The high-water marks
below were observed during reconnaissance on 2026-05-03 and seed the
speculative driver.

| Site type | Format | Yearly? | Example | Approx. high seed (2026) |
|-----------|--------|---------|---------|--------------------------|
| `fc` (SJC Full Court) | `SJC-NNNNN` | No (continuous) | `SJC-13927` | ~13950 |
| `oe` (SJC Original Entry) | `OE-NNNN` | No (continuous) | `OE-0157` | ~160 |
| `sj` (SJC Single Justice) | `SJ-YYYY-NNNN` | Yes | `SJ-2025-0518` | ~600/yr |
| `ar` (SJC DAR/FAR Applications) | `FAR-NNNNN` (also `DAR-NNNNN`) | No (continuous) | `FAR-30715` | ~30750 |
| `bd` (SJC Bar Docket) | `BD-YYYY-NNN` | Yes | `BD-2025-004` | ~10/yr typical |
| `ac` (Appeals Court Panel) | `YYYY-P-NNNN` | Yes | `2025-P-1489` | ~1700/yr |
| `aj` (Appeals Court Single Justice) | `YYYY-J-NNNN` | Yes | `2025-J-0972` | ~1100/yr |

Notes:
- A `B` suffix sometimes appears on FAR/DAR numbers (e.g. `FAR-30464B`).
  These are companion applications attached to the same underlying lower
  case; we surface them only when discovered via party search since the
  speculative driver does not enumerate them.
- All docket-number patterns are zero-padded to a fixed width when used
  in URLs.

## Data Available

All case data lives on a single page at `GET /docket/{docket_id}`. There
are no tabs, no AJAX sub-resources, and no expandable accordions. The
following sections always appear, though their exact field set varies
slightly between case-type categories.

### Case Header (always present)

Common fields:

- `Case Status` — e.g. *Active: Case Filed*, *Decided, Rescript issued*,
  *FAR denied*, *Disposed: Case Closed*
- `Status Date` — `MM/DD/YYYY`
- `Nature` — case nature/subject (e.g. *Equity*, *Murder1 appeal*)
- `Entry Date` — `MM/DD/YYYY`, the date the case was entered
- `Appellant` — *Plaintiff* / *Defendant* / *Petitioner* etc.
- `Case Type` — *Civil* / *Criminal*
- `Brief Status`, `Brief Due` — string text
- `Citation` — e.g. `492 Mass. 604`
- `Lower Court`, `TC Number` (or `Lower Ct Number`), `Lower Ct Judge`,
  `TC Entry Date`

Fields that vary by category:

- SJC Full Court adds: `Quorum`, `Argued Date`, `Decision Date`,
  `AC/SJ Number`, `DAR/FAR Number`, `Route to SJC`
- Appeals Court Panel adds: `Panel`, `Arg/Submitted`, `Decision Date`,
  `SJ Number`, `FAR Number`, `SJC Number`
- DAR/FAR cases add: `Appeals Ct Number`, `Response Date`, `Applicant`,
  `Full Ct Number`
- Original Entry adds: `Quorum`, `Full Ct Number`

We capture all of these into a single broad `MaDocket` model with
`Optional` fields rather than splitting per-category.

### Additional Information (sometimes present)

A free-text block ("ADDITIONAL INFORMATION") sometimes appears between
the case header and the parties. Captured as `additional_information: str`.

### Future Calendar (sometimes present)

When a case is scheduled for argument, a "FUTURE CALENDAR" block lists
date, time, presiding panel, and courthouse room. Captured as a list of
`MaScheduledHearing` rows.

### Involved Party / Attorney Appearance

Two-column layout: each party has a name, a role (e.g.
*Plaintiff/Appellant*, *Pro Se Defendant/Petitioner*, *Other interested
party*), optional brief-status string ("Blue br, app & reply br filed"),
and optional enlargement summary ("2 Enls, 28 Days"). Each party block
lists 0+ attorneys; attorneys may carry a "- Withdrawn" suffix and link
to `/attorney/{id}` (the link itself we do not follow during normal
scraping).

### Documents (sometimes present)

A "DOCUMENTS" block lists `<a href="/pdf/{docket_id}/{filename}.pdf">`
links. Each link has a label (e.g. "Appellant Smith Brief"). We yield
each as a separate `MaDocument` with `archive=True`.

### Docket Entries (almost always present)

Three-column table: `Entry Date | Paper | Entry Text`.

- `Entry Date` — `MM/DD/YYYY`
- `Paper` — empty string for clerk notations, or `#N` for filed papers
- `Entry Text` — free text

## Email Notifications

The site does **not** advertise an email-notification subscription. There
is no "subscribe" link on case pages and the help/feedback links go only
to `feedback@ma-appellatecourts.org`. **Not implemented.**

## Oral Arguments Calendar

Available at `/calendar/{fc,sj,ac,aj}` but limited to the *current
month*. There is no month-picker and the URL pattern
`/calendar/{type}/{year}/{month}` redirects to `/`.

We add an `MaOralArgument` model and a single calendar entry point per
calendar type that scrapes the current-month listing. Backfilling older
months is not possible without bulk historical data from the court.

## Bot Protection Notes

- **Cloudflare managed challenge** — every page load is gated on a JS
  challenge. The scraper must run under `JS_EVAL` + `FF_ALIKE`.
- **CSRF token** — `<input type="hidden" name="_token" value="...">`
  inside each search form must be re-posted on every search submission.
  We obtain it by GETting the form page first (`page.find_form()`
  preserves it automatically through `form.submit()`).
- **Sessions** — search results are paged via `?page=N` against a
  session-stored search; the scraper must keep the cookie jar live
  through pagination or re-issue the POST for each page. Speculative
  per-case GETs avoid the issue entirely.

## Scraper Architecture

### Entry Points

We use **only speculative entries** for the primary harvest. One entry
per case-type category so the driver can advance each independently.

Sequential (continuous numbering, `SpeculativeRange`):

- `fetch_sjc_full_court_docket` → `SJC-NNNNN` (court_id `mass`)
- `fetch_sjc_original_entry_docket` → `OE-NNNN` (court_id `mass`)
- `fetch_sjc_far_application_docket` → `FAR-NNNNN` (court_id `mass`)

Yearly (resets each calendar year, `YearlySpeculativeRange`):

- `fetch_sjc_single_justice_docket` → `SJ-YYYY-NNNN`
- `fetch_sjc_bar_docket` → `BD-YYYY-NNN`
- `fetch_appeals_panel_docket` → `YYYY-P-NNNN`
- `fetch_appeals_single_justice_docket` → `YYYY-J-NNNN`

Each speculative entry returns a single `Request` for `GET
/docket/{docket_id}`.

We additionally expose four oral-argument calendar entries (one per
calendar type) since those pages are scrape-and-parse current-month
snapshots:

- `get_sjc_full_court_calendar` → `MaOralArgument` rows
- `get_sjc_single_justice_calendar`
- `get_appeals_panel_calendar`
- `get_appeals_single_justice_calendar`

### Step Functions

```
fetch_*_docket → parse_case_detail
                   ├── yields MaDocument archive Requests for each PDF link
                   └── yields ParsedData(MaDocket)

handle_document_download → yields ParsedData(MaDocument)

get_*_calendar → parse_calendar
                   └── yields ParsedData(MaOralArgument) per scheduled case
```

### Soft-404 Detection

When a docket does not exist the server **redirects** to the search
landing page (`/docket`, `/`, etc.), not a 404. We override
`fails_successfully` to detect this — a successful detail page contains
the heading "Case Docket" inside the `<main>` element.

### Models

- `MaDocket` — main per-case output
- `MaDocketEntry` — per-row in the docket-entries table
- `MaParty` — name, role, brief status, attorneys
- `MaAttorney` — name, optional firm/title, withdrawn flag
- `MaDocument` — PDF download (archived)
- `MaScheduledHearing` — entry in the FUTURE CALENDAR block
- `MaOralArgument` — top-level output from calendar pages
