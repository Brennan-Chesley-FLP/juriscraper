# Pennsylvania UJS Portal (Appellate) Scraper Design

## Site Overview

- **Base URL**: https://ujsportal.pacourts.us/CaseSearch
- **Requires Playwright**: No — server-rendered HTML, plain `<form method="POST">`,
  `__RequestVerificationToken` (ASP.NET Core anti-forgery) handled by re-issuing
  a GET to the form page and forwarding the hidden field through `find_form().submit()`.
- **Transport**: HTML form POST. Response is the same `/CaseSearch` page with the
  results table (`#caseSearchResultGrid`) rendered inline.
- **Detail surface**: there is no per-case HTML detail page. The only structured
  per-case artifact is a Crystal-Reports-rendered PDF "docket sheet" reachable
  at `/Report/PacDocketSheet?docketNumber=<DN>&dnh=<HASH>`. The `dnh` (docket
  number hash) is a per-docket signature embedded in the search results row;
  it must be captured from the row HTML — there is no way to derive it.
  Once captured the PDF download is unauthenticated (cookies optional).

## Courts Covered

The "Search By: Appellate" dropdown exposes three appellate courts. The site
uses the same `/CaseSearch` form for all three; selection is a single
`AppellateCourtName` form field.

| Site value (`AppellateCourtName`) | Display Name | CourtListener ID |
|---|---|---|
| `Supreme` | Supreme Court of Pennsylvania | `pa` |
| `Superior` | Superior Court of Pennsylvania | `pasuperct` |
| `Commonwealth` | Commonwealth Court of Pennsylvania | `pacommwct` |

PA courts have districts (Eastern / Middle / Western), but those map *into the
docket number* (see below) rather than to separate CourtListener IDs.

## Search Capabilities

Two entry points are needed per the user request:

1. **Date-range entry** — `Search By = Appellate`. Required field
   `AppellateCourtName ∈ {Supreme, Superior, Commonwealth}`; optional
   `FiledStartDate` / `FiledEndDate` (`YYYY-MM-DD` from the
   `<input type="date">` widget).
2. **Docket-number entry** — `Search By = DocketNumber`. Single field
   `DocketNumber` (e.g. `44 WM 2026`). Returns 0 or 1 row; matches across all
   courts (appellate + trial), so this is the single-docket lookup.

**Result cap**: empirically, the result grid is capped at **500 rows** per
search regardless of date range (a 1-month, 6-month, and 1-year Superior
search all returned exactly 501 `<tr>` in the tbody — header + 500 data rows
under the multi-row carousel layout). The scraper splits date ranges if the
returned row count is at the cap.

**Pagination**: none — there is no "next page" link. The cap-and-split
strategy above is the only available mechanism. With ~250 Superior cases per
month observed, a 1-month window stays comfortably under the cap; smaller
windows are used as a safety margin (see scraper.py for the actual chunking).

**Decision-tree result**: date-range filter exists and works (option 1 in the
skill's decision tree). Speculative entry not needed.

## Docket Number Formats

Format is `<seq> <type> <year>` separated by spaces, where `<type>` is a
2–3-letter prefix encoding court + district + case-type. Seq is per
(court, type, year), resets yearly. Year is a literal 4-digit calendar year.

Per-court prefixes observed (April 2026 sample, ~190–250 results each):

| Court | Prefix examples | Meaning (approximate) |
|---|---|---|
| Supreme | `WM`, `EAL`, `WAL`, `MAL`, `EAP`, `WAP`, `MAP`, `MM`, `EM` | E/M/W = Eastern/Middle/Western district; AL = Allocatur (petition for allowance of appeal), AP = Appeal, M = Miscellaneous |
| Superior | `EDA`, `MDA`, `WDA` | E/M/W District Appeal |
| Commonwealth | `MD`, `CD`, `MAP`, `CAP` | Middle Docket / Civil Docket / Misc/Appeal variants |

The scraper does **not** parse the prefix — the docket number is treated as
an opaque string captured verbatim from the search row. The court is set
from the form-side `AppellateCourtName` filter on the date-range path, and
inferred from the row's "Court Type" cell + the docket number prefix on the
single-docket path (see `scraper.py:_court_id_from_docket_number`).

## Data Available

### Search Results Grid (per row)

The `#caseSearchResultGrid` table exposes 19 columns; for appellate rows
most trial-court columns are blank. Useful columns:

- Docket Number (e.g. `44 WM 2026`)
- Court Type (`Appellate` for our targets)
- Case Caption (e.g. `In Re: Bar App. of Alicia Christina Bogda`)
- Case Status (`Active`, `Closed`, etc.)
- Filing Date (MM/DD/YYYY)
- Primary Participant(s)
- Date Of Birth(s) (rarely populated for appellate)
- County, Court Office, OTN, Complaint #, Incident # (mostly blank for appellate)
- Event Type / Event Status / Event Date / Event Location (next scheduled
  hearing if any — populated only for cases with upcoming events)
- Docket Sheet link → `/Report/PacDocketSheet?docketNumber=<DN>&dnh=<HASH>`

### Docket Sheet PDF (`/Report/PacDocketSheet`)

This is the only per-case detail surface. The PDF is a Crystal Reports export
containing — by inspection of sample dockets — the full register of actions,
parties, attorneys, dispositions, and trial-court history. Two pages, ~96 KB
average. Content is image-rendered text (extractable with a downstream PDF
parser — out of scope for this scraper).

The scraper archives the PDF and emits a `PADocketSheetPDF` model with the
local filepath. Parsing the PDF into structured docket entries / parties is
explicitly post-hoc and lives outside this scraper.

## Email Notifications

Not available — the public CaseSearch surface has no per-case subscribe
affordance.

## Oral Arguments Calendar

The "Calendar Event" Search By option exists and accepts a date range, but it
returns scheduled events (any court, including trial courts) rather than a
per-court oral-argument calendar. Not pursued in v1 — the user-requested
entry points (Docket-number + Appellate date range) are the priority.

## Bot Protection Notes

- **`__RequestVerificationToken`**: ASP.NET Core anti-forgery token rendered
  as a hidden input on the GET response. Required on POST or the server
  returns HTTP 400. `find_form().submit()` propagates it automatically.
- **Cookies**: a session cookie is set on first GET. Empirically the POST
  succeeds without cookies as long as the token is present, but kent's
  default httpx driver shares a cookie jar within a scrape, so this is a
  no-op concern.
- **PDF download**: the `dnh` hash is the only authorization for the
  `/Report/PacDocketSheet` endpoint. No session needed.

## Known Gaps

- **PDF parsing**: PDFs are archived but not parsed. A downstream parser is
  expected to consume `PADocketSheetPDF.local_path` and emit register-of-
  actions / party / disposition records. The scraper does not bridge that.
- **500-row cap**: handled by date-range halving on the date-range entry
  path; a single split is done eagerly when the cap is hit. For courts with
  filing rates that could exceed 500/day (none currently observed) this
  would need finer chunking.

## Scraper Architecture

### Entry Points

- `get_docket(docket_number: str)` — single-docket lookup. Searches
  `SearchBy=DocketNumber`. Yields a `PADocket` from the (single) result row,
  plus an archive `Request` for the docket-sheet PDF. The PDF archive
  continuation emits a `PADocketSheetPDF`.
- `get_appellate_dockets_by_date(court: PACourtParam, date_range: DateRange)`
  — date-range scrape per appellate court. Submits the form for the given
  court + window. If the result count reaches the 500-row cap, splits the
  window in half and re-issues. Yields one `PADocket` per row plus one
  archive `Request` per row.

### Step Functions (flow)

```
get_docket
  → fetch_search_page (GET / for token & form)
    → submit_docket_search        (POST /CaseSearch with DocketNumber)
      → parse_results              (yield PADocket + archive Request)
        → handle_docket_sheet_pdf  (archive=True → yield PADocketSheetPDF)

get_appellate_dockets_by_date
  → fetch_search_page (GET / for token & form)
    → submit_appellate_search     (POST /CaseSearch with court + dates)
      → parse_results              (yield PADocket + archive Request,
                                    or split & re-submit if at cap)
        → handle_docket_sheet_pdf  (archive=True → yield PADocketSheetPDF)
```

`parse_results` is shared between both flows. Cap-detection (`len(rows) >= 500`)
triggers a recursive split on the date-range path only — single-docket has at
most one row.

### Models

- `PADocket` — the per-row case record (court_id, docket_number, case_name,
  date_filed, case_status, primary_participants, scheduled_event, source_url).
- `PADocketSheetPDF` — the archived PDF descriptor (court_id, docket_number,
  document_url, local_path). Reached only via the `archive=True` step so the
  driver injects `local_filepath`.

`PADocketSheetPDF` is intentionally named with a `PDF` suffix to make it
easy to distinguish from any future structured-docket-entry models that may
parse the same PDF post-hoc.

## Reference: form fields actually sent

Captured by sniffing the live form POST. The site sends every form field in
the page, even the hidden / inactive ones; only the relevant ones are listed
here.

**Date-range search:**

```
SearchBy=AppellateCourtName
AppellateCourtName=Supreme|Superior|Commonwealth
FiledStartDate=YYYY-MM-DD
FiledEndDate=YYYY-MM-DD
__RequestVerificationToken=<token>
```

**Docket-number search:**

```
SearchBy=DocketNumber
DocketNumber=<docket number, spaces preserved>
__RequestVerificationToken=<token>
```

`find_form().submit()` carries every other hidden field through unchanged,
which is the recommended path on ASP.NET Core sites with anti-forgery.
