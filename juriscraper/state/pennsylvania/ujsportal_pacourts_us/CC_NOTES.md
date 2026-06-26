# Pennsylvania UJS Portal (Appellate) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Three appellate courts (`pa`, `pasuperct`, `pacommwct`) behind one
> server-rendered ASP.NET Core form. Plain HTTP (`driver_requirements = []`),
> no JS challenge and no captcha — the only stateful piece is the
> `__RequestVerificationToken` anti-forgery hidden field, carried from the
> form GET to the search POST by `find_form().submit()`. Per-row HTML
> extraction lives in the `parsers/` package (§9, `ResultsGridParser`);
> steps keep navigation (the GET/POST handshake, the per-row PDF archive
> fan-out, the result-cap date-range split). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `case_name` (not `case_caption`), `date_*` date naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: https://ujsportal.pacourts.us/CaseSearch
- **Backend**: ASP.NET Core, server-rendered HTML, plain `<form method="POST">`.
- **Requires Playwright**: No — server-rendered HTML, no JS challenge.
- **Transport**: HTML form POST. The response is the same `/CaseSearch` page
  with the results table (`#caseSearchResultGrid`) rendered inline.
- **Detail surface**: there is no per-case HTML detail page. The only
  structured per-case artifact is a Crystal-Reports PDF "docket sheet" at
  `/Report/PacDocketSheet?docketNumber=<DN>&dnh=<HASH>`. The `dnh` (docket
  number hash) is a per-docket signature embedded in the search-results row;
  it must be captured from the row HTML — there is no way to derive it. Once
  captured the PDF download is unauthenticated (cookies optional), but the
  endpoint 401s on httpx's default User-Agent, so a browser UA is sent via
  `Request.permanent` headers on every request.

## Courts Covered

| Site value (`AppellateCourtName`) | Display name | CourtListener ID |
|---|---|---|
| `Supreme` | Supreme Court of Pennsylvania | `pa` |
| `Superior` | Superior Court of Pennsylvania | `pasuperct` |
| `Commonwealth` | Commonwealth Court of Pennsylvania | `pacommwct` |

PA courts have districts (Eastern / Middle / Western), but those map *into
the docket number* (the type prefix) rather than to separate CourtListener
IDs.

## Search Capabilities

- **Date-range search** — `SearchBy=AppellateCourtName`. Required field
  `AppellateCourtName ∈ {Supreme, Superior, Commonwealth}`; optional
  `FiledStartDate` / `FiledEndDate` (`YYYY-MM-DD`). The site searches one
  court per POST, so `dockets_by_filing_date` seeds one search per requested
  court.
- **Docket-number search** — `SearchBy=DocketNumber`. Single field
  `DocketNumber` (e.g. `44 WM 2026`). Returns 0 or 1 row; matches across all
  courts.

**Result cap**: the results grid is capped at **500 data rows** per search
regardless of date range (a 1-month, 6-month, and 1-year Superior search all
returned exactly 500 data rows). `parse_results` splits the date range in
half and resubmits both halves when a date-range search hits the cap, down
to a 1-day floor.

**Pagination**: none — there is no "next page" link. The cap-and-split
strategy is the only available mechanism.

## Docket Number Format

`<seq> <type> <year>` separated by spaces, where `<type>` is a 2–3-letter
prefix encoding court + district + case-type. Seq is per (court, type, year)
and resets yearly. The scraper treats the docket number as an opaque string
captured verbatim. On the date-range path the `court` is the form-side
`AppellateCourtName` filter; on the single-docket path the caller's
`court_id` argument is stamped onto the record.

## Data Available

### Search-results grid (per row → `PADocket`)

`#caseSearchResultGrid` exposes 19 columns; for appellate rows most
trial-court columns are blank. Captured: docket number, court type, case
caption (→ `case_name`), case status, filing date (→ `date_filed`), primary
participant(s), county, court office, OTN, complaint #, incident #, next
event type/status/date/location, and the docket-sheet PDF link.

### Docket-sheet PDF (`/Report/PacDocketSheet` → `PADocketSheetPDF`)

The only per-case detail surface — a Crystal Reports export containing the
full register of actions, parties, attorneys, dispositions, and trial-court
history. The scraper archives the PDF and emits a `PADocketSheetPDF` with the
local filepath; parsing the PDF into structured records is explicitly
post-hoc and lives outside this scraper.

## Out of Scope

- **PDF parsing**: PDFs are archived but not parsed.
- **Calendar Event search**: exists and accepts a date range, but returns
  scheduled events for any court (including trial courts) rather than a
  per-court oral-argument calendar. Not pursued.
- No per-case email-notification / subscribe affordance.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|---|---|---|
| `dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | One date-range search POST per requested appellate court; cap-split on 500 rows. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Single-docket lookup; matches across all courts. |

For a full backfill, run `dockets_by_filing_date` over a wide window for the
target courts.

### Step functions and priorities (§5)

```
dockets_by_filing_date → submit_appellate_search (4) → parse_results (3)
                                                        ├→ handle_docket_sheet_pdf (1, archive)
                                                        └→ (cap) split & resubmit → parse_results (3)
docket_by_number       → submit_docket_search    (4) → parse_results (3)
                                                        └→ handle_docket_sheet_pdf (1, archive)
```

Priorities descend by depth so in-flight searches finish before new ones
start. The PDF archive request is the only download; `archive=True`
auto-assigns priority 1.

### Deduplication keys (§6)

- `appellate_search_seed:<court>:<start>:<end>` / `docket_search_seed:<dn>` —
  the form-GET seed.
- `appellate_search:<court>:<start>:<end>` / `docket_search:<dn>` — the
  search POST.
- `<court>-<docket_number>.pdf` — the PDF archive (colon-free; becomes a
  filename). Dedups the same docket surfaced by both entry paths.

### HTTP status handling (§10)

`HTTP_CODE_TYPES = {400: HTTPCodeType.TRANSIENT}` — the portal intermittently
400s (~1%) on well-formed POSTs with a fresh anti-forgery token; reclassify
as transient so they retry instead of dropping the date window's rows.

### Data types

`PADocket` (main, → CL `Docket`) and `PADocketSheetPDF` (the archived,
unparsed docket-sheet PDF descriptor).
