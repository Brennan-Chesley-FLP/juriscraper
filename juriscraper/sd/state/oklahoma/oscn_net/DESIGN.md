# OSCN (oscn.net) Scraper Design

## Site Overview
- **Base URL**: https://www.oscn.net
- **Server**: Microsoft IIS 10 (ASP.NET, server-rendered HTML)
- **Requires Playwright**: No — `httpx`/`curl` returns full HTML in a single
  request. Cloudflare *can* be in front of the site (the user has reported
  occasional interstitials in their browser). When that happens we detect
  the challenge body and raise `TransientException` so the driver retries.

## Courts Covered

The OSCN appellate dockets database (`db=appellate`) serves all Oklahoma
appellate courts in a single backend. The actual court is identified by the
case caption heading on each case page.

| Caption heading                                                   | CourtListener ID |
| ----------------------------------------------------------------- | ---------------- |
| `IN THE SUPREME COURT OF THE STATE OF OKLAHOMA`                   | `okla`           |
| `IN THE COURT OF CIVIL APPEALS OF THE STATE OF OKLAHOMA`          | `oklacivapp`     |
| `IN THE COURT OF CRIMINAL APPEALS OF THE STATE OF OKLAHOMA`       | `oklacrimapp`    |
| `IN THE COURT ON THE JUDICIARY...`                                | `oklacoj`        |
| `OKLAHOMA JUDICIAL ETHICS ADVISORY PANEL`                         | `oklajeap`       |

The lower court database is keyed by Oklahoma county name (lowercase): the
URL `?db=tulsa&number=CV-2020-84` returns the trial-court docket page in the
same HTML format as appellate dockets.

## Search Capabilities

| Rank | Mode | Notes |
|------|------|-------|
| 1 | Date-based search | `Results.aspx?db=appellate&FiledDateL={MM/DD/YYYY}&FiledDateH={MM/DD/YYYY}` returns a single HTML table of every case filed in the window |
| 2 | Case number lookup | `GetCaseInformation.aspx?db=appellate&number={case_number}` |
| 3 | Party name search | Same form, `lname`/`fname`/`mname` |

The result table rows are `<tr class="resultTableRow oddRow|evenRow">`
with cells `result_casenumber`, `result_datefiled`, `result_shortstyle`,
`result_info`. Results are sorted by filed-date ascending.

**500-row cap** — `Results.aspx` truncates every response at 500 rows
regardless of the requested range. When the cap is hit, the page
includes the visible warning:

> The results are limited to 500 records in order to preserve server
> resources for other users.

The scraper detects this marker in `parse_search_results` and resumes
the scan with a follow-up request for `(latest_date_shown,
original_end_date)`, keeping the boundary day inclusive so any
overflow on that day is captured. Per-case dedup filters duplicates
from the overlap.

If the cap message is present *and* every row on the page shares the
same filed-date, date bisection cannot subdivide further; the scraper
raises `SearchVolumeAssumptionError` (a `ScraperAssumptionException`
subclass defined in this module).

**Recommended approach**: date-range entry — split a configurable window
across the date_filed range. Default to 7-day chunks scanning back as far as
the user requests.

## Docket Number Formats (Appellate)

Examples observed in `db=appellate`:

| Prefix | Meaning | Example |
|--------|---------|---------|
| `SCBD-` | Supreme Court Bar Discipline | `SCBD-8100` |
| `SCAD-` | Supreme Court Administrative Directive | `SCAD-2026-25` |
| `IP-` | Initiative Petition | `IP-123982` |
| `DF-` | Domestic forfeiture | `DF-121868` |
| `(numeric)` | Generic appellate case number | `121868` |

The case-page JSON `<script id="json_style">` block also exposes a
canonical `casenumber` (e.g., `DF-121868`) which differs from the URL's
`number=` parameter (`121868`) for some case types — always prefer the
JSON-block value.

## Data Available

Each case page (`GetCaseInformation.aspx`) is a single HTML document with
the sections below.

### `<script id="json_style">` (case metadata block)
Embedded JSON object with: `casenumber`, `style` (short caption), `cmid`,
`cms`, `court` (UPPERCASE court database name, e.g. `APPELLATE`).

### Case heading
- `<h2>` containing the court name (e.g.
  `IN THE COURT OF CIVIL APPEALS OF THE STATE OF OKLAHOMA Tulsa`).
- A two-cell table with: case caption text + `(case number, classification,
  filed date, opinion citation link)`.
- "Filed Opinion/Order" with citation link to
  `http://www.oscn.net/applications/oscn/deliverdocument.asp?citeid=NNNNNN`.

### Track Case button (JS-injected)
The `casetracker.js` script reads embedded JS variables `court` and
`casenumber`, then constructs:
`https://app.oscn.net/cases/?act={COURT_UPPER}&acn={case_number}`
We capture this URL ourselves rather than executing the JS.

### Parties (`<h2>Parties</h2>`)
A `<p>` with one `<span class="parties_party">` per party. Each contains
`parties_partyname` and `parties_type` (role).

### Attorneys (`<h2>Attorneys</h2>`)
Two-column table: attorney name + bar number + multi-line address; and a
list of represented party names.

### Events (`<h2>Events</h2>`)
Often `None`. When present, scheduled hearings/events with date and
description.

### Lower Court Counts and Other Information
Table with columns: `Count`, `Case Number`, `Statute`, `Crime`, `Sentence`,
`Judge`, `Reporter`. Rows describe the originating trial-court counts. The
case-number cell is plain text (no link) but a follow-up fetch using
`?db={county}&number={case_number}` (county derived from the appellate
caption suffix or page heading) returns the trial-court docket page.

### Docket (`<h2>Docket</h2>`)
A table with columns `Date`, `Code`, `Description`, `Count`, `Party`,
`Amount`. Each row is `<tr class="docketRow oddRow|evenRow primary-entry">`.

Inside each cell, content is wrapped in `<font color="...">` tags. The
hex color encodes (presumably) entry significance and varies across
entries. Observed colors include `0000FF` (blue), `000000` (black),
`228B22` (forest green), `DAA520` (goldenrod), `FF8C00` (dark orange),
`FFD700` (gold), `FF0000` (red). We capture the color as a hex string on
each entry.

When a docket entry has a document, the description cell contains
`Document Available (#NNNNNNN)` followed by two anchor tags:
- `<a href="GetDocument.aspx?ct=appellate&cn={case_number}&bc={doc_id}&fmt=tif">TIFF</a>`
- `<a href="GetDocument.aspx?ct=appellate&bc={doc_id}&cn={case_number}&fmt=pdf">PDF</a>`

Both formats are downloaded and archived (`Request(archive=True)`).

## Document Downloads

`GetDocument.aspx` returns the binary directly with
`Content-Disposition: attachment; filename={doc_id}-{date}-{seq}.{ext}`.
Tested: returns 200 OK with `application/pdf` (~1 MB) for SCBD-8100/1064718957.

## Lower Court Case Resolution

Algorithm for following the lower-court link:
1. The appellate case heading appends a county/location hint after the
   court name (e.g., `... OF THE STATE OF OKLAHOMA Tulsa`).
2. Use the trailing token, lowercased, as the `db` parameter.
3. Fetch `GetCaseInformation.aspx?db={county}&number={lower_court_case_number}`.
4. Parse the same HTML schema. If the response 404s or returns the OSCN
   "case not found" page, record only the structured Lower Court Counts
   table data and continue.

## Track Case URL

`https://app.oscn.net/cases/?act={COURT_UPPER}&acn={case_number}` where:
- `COURT_UPPER` is the uppercased `court` value from the embedded
  `json_style` block (typically `APPELLATE` for appellate cases, or the
  county uppercased for trial cases).
- `case_number` is the canonical `casenumber` from the `json_style` block.

## Cloudflare / Transient Detection

`curl` against the site currently succeeds (no interstitial), but the user
has reported occasional Cloudflare challenge pages. Each step that parses
HTML calls a shared `_check_cloudflare_interstitial` helper that raises
`TransientException` if it detects:
- Page title containing "Just a moment..." / "Attention Required" /
  "Sorry, you have been blocked"
- `<div id="cf-wrapper">` / `<div class="cf-error-details">`
- Body containing the `challenge-platform` script reference
- Response status 403/503 with a `cf-ray` header

Driver will retry on `TransientException`.

## Bot Protection / Hidden Fields

None observed beyond standard ASP.NET viewstate (the `Search.aspx` form
posts to `Results.aspx` with simple GET parameters; viewstate is not
required for `Results.aspx` directly).

## Email / Subscription Notifications

The case page exposes a "Get Text Reminders" panel that sends
`SUBSCRIBE {county_code}{case_number_no_dashes}` to `1-877-849-0889`.
This is a personal opt-in mechanism, not a structured feed; we don't
implement it.

## Oral Arguments Calendar

OSCN does not publish a queryable oral-argument calendar in the docket
section. Hearings/events appear on each case page under `<h2>Events</h2>`
when present. We'll capture these as `OkEvent` records nested in the
docket. No separate `oral_arguments` data type is exposed.

## Scraper Architecture

### Entry Points

| Method | Param | Purpose |
|--------|-------|---------|
| `get_dockets` | (none) | Date-range scan; defaults to last 7 days |
| `get_dockets_by_date` | `DateRange` | Explicit start/end |
| `fetch_docket` | (`OkDocket.case_number`, `OkDocket.court_id`) | Direct lookup by case number — uses `_params` |

### Step Functions
```
get_dockets / get_dockets_by_date
  -> _yield_search_request (chunks date range)
     -> parse_search_results (extracts case number links, soft-404 detect)
        -> parse_case_detail (parses appellate page, yields lower-court request)
           -> parse_lower_court_case (parses trial-court page)
              -> assemble_docket -> ParsedData(OkDocket)
                                 -> Request(archive=True) per TIFF + PDF
```

Because each appellate case may produce many archive requests (TIFF + PDF
per docket entry, plus the Filed Opinion link), document archives are
yielded alongside `ParsedData` from `parse_case_detail` (or its lower-court
follow-up step). The driver handles them with `archive=True`.

### Models
- `OkDocketEntry` — date_filed, code, description, color, document_id,
  tiff_url, pdf_url
- `OkParty` — name, role
- `OkAttorney` — name, bar_number, address, represented_parties
- `OkLowerCourtCount` — count, case_number, statute, crime, sentence,
  judge, reporter
- `OkLowerCourtCase` — court_db, case_number, case_name, date_filed,
  parties, attorneys, entries, source_url
- `OkEvent` — date, description (scheduled hearings / events)
- `OkDocket` — main case data, includes nested lists above plus
  `opinion_url`, `opinion_citation`, `track_case_url`, `source_url`,
  `cmid`, `case_classification`
