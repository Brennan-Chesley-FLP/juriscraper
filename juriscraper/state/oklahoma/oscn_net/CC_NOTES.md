# Oklahoma State Courts Network (oscn.net) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> One backend (`db=appellate`) serves all five Oklahoma appellate courts;
> the actual court is detected per-case from the caption heading and mapped
> to a CourtListener id. Plain-HTTP ASP.NET site (`driver_requirements =
> []`). HTML extraction lives in the `parsers/` package (§9,
> `SearchResultsParser` / `CaseDetailParser`); steps keep navigation
> (date-window chunking, the 500-row cap resume, the per-case fan-out, and
> the lower-court follow-up). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `case_number`, with `docket_number_raw`), `date_*`
> naming, `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://www.oscn.net`
- **Backend**: Microsoft IIS 10 / ASP.NET, server-rendered HTML.
- **Requires Playwright**: No — `httpx`/`curl` returns full HTML in one
  request. Cloudflare *can* front the site (the user reports occasional
  interstitials). Each parsing step calls `_check_cloudflare_interstitial`,
  which raises `TransientException` on a challenge body / `cf-ray` 403/503 so
  the driver retries rather than treating the page as a real not-found.

## Courts Covered

The OSCN appellate dockets database (`db=appellate`) serves all Oklahoma
appellate courts in a single backend; the court is identified from the case
caption heading.

| Caption heading                                              | CourtListener ID |
| ------------------------------------------------------------ | ---------------- |
| `IN THE SUPREME COURT OF THE STATE OF OKLAHOMA`              | `okla`           |
| `IN THE COURT OF CIVIL APPEALS OF THE STATE OF OKLAHOMA`     | `oklacivapp`     |
| `IN THE COURT OF CRIMINAL APPEALS OF THE STATE OF OKLAHOMA`  | `oklacrimapp`    |
| `IN THE COURT ON THE JUDICIARY ...`                          | `oklacoj`        |
| `OKLAHOMA JUDICIAL ETHICS ADVISORY PANEL`                    | `oklajeap`       |

The lower-court database is keyed by Oklahoma county name (lowercase): the
URL `?db=tulsa&number=CV-2020-84` returns the trial-court docket page in the
same HTML format as appellate dockets.

## Search Capabilities

| Rank | Mode | Notes |
|------|------|-------|
| 1 | Date-range search | `Results.aspx?db=appellate&FiledDateL={MM/DD/YYYY}&FiledDateH={MM/DD/YYYY}` returns one HTML table of every case filed in the window |
| 2 | Case-number lookup | `GetCaseInformation.aspx?db=appellate&number={docket_number}` |

Result rows are `<tr class="resultTableRow oddRow|evenRow">` with cells
`result_casenumber`, `result_datefiled`, `result_shortstyle`,
`result_info`, sorted by filed-date ascending.

**500-row cap** — `Results.aspx` truncates every response at 500 rows and
prints `The results are limited to 500 records ...`. The scraper splits the
requested range into 7-day windows; on a cap hit within a window it resumes
with a follow-up search for `(latest_date_shown, original_end_date)` (boundary
day inclusive), with per-case dedup filtering the overlap. If the cap is hit
*and* every row shares one filed-date, date bisection cannot subdivide
further and the scraper raises `SearchVolumeAssumptionError`.

## Docket Number Format (Appellate)

Examples in `db=appellate`: `SCBD-8100` (bar discipline), `SCAD-2026-25`
(administrative directive), `IP-123982` (initiative petition), `DF-121868`,
or a bare numeric. The case page's `<script id="json_style">` block exposes
a canonical `casenumber` that can differ from the URL `number=` parameter for
prefixed case types — always prefer the JSON-block value (`docket_number`).

## Data Available

Each case page (`GetCaseInformation.aspx`) is one HTML document.
`CaseDetailParser` extracts:

- **`<script id="json_style">`** — `casenumber`, `style`, `cmid`, `court`
  (UPPERCASE backend name, e.g. `APPELLATE`). Read via the script node's
  `text_content()` (keeps `from_string`/`from_file` offline tests working).
- **Heading** (`<h2>...STATE OF OKLAHOMA[ County]>`): court id + county hint.
- **Caption row**: `case_name`, `case_classification` (parenthetical),
  `date_filed` (`Filed:` token), opinion link/citation.
- **Parties** (`<h2>Parties</h2>`): `OkParty` (name, role).
- **Attorneys** (`<h2>Attorneys</h2>`): `OkAttorney` (name, bar_number,
  multi-line address, represented_parties). Address lines are reconstructed
  from `inner_html()` split on `<br>` (public API — no `._element` access).
- **Events** (`<h2>Events</h2>`): `OkEvent` (date_event, description) —
  scheduled hearings live here, modelled on the docket, not a separate type.
- **Lower Court Counts**: `OkLowerCourtCount` rows (count, docket_number,
  statute, crime, sentence, judge, reporter).
- **Docket** (`<tr class="docketRow ...">`): `OkDocketEntry` rows (date_filed,
  code, description, color hex, count, party, amount, document_id, tiff_url,
  pdf_url). `Document Available (#NNNN)` rows carry `GetDocument.aspx`
  TIFF/PDF anchors, archived via `Request(archive=True)`.

### Track Case URL

Built ourselves from the `json_style` block (no JS executed):
`https://app.oscn.net/cases/?act={COURT_UPPER}&acn={docket_number}`.

### Lower-court resolution

When the appellate caption heading appends a known county token, the scraper
fetches `GetCaseInformation.aspx?db={county}&number={lower_court_number}` (the
first usable Lower Court Counts number) and parses it with the same
`CaseDetailParser` section methods into a nested `OkLowerCourtCase`. A
populated `json_style.casenumber` is used as the real-page signal (vs a
soft-404 stub); on a miss the appellate docket is emitted with only the
structured Lower Court Counts.

## Out of Scope

- Party-name search, the SMS "Get Text Reminders" subscribe panel, and the
  oral-argument calendar (hearings already appear per-case under Events).

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_filing_date(court_ids, date_range)` | `DateRange` | Date-range scan; one `Results.aspx` request per 7-day window. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Direct lookup of one known appellate case number. |

For a backfill, run `dockets_by_filing_date` over the desired window.

### Step functions and priorities (§5)

```
dockets_by_filing_date → parse_search_results (3) → parse_case_detail (2)
                                                  └→ (per case)
                                       parse_case_detail (2) → parse_lower_court_case (2)
                                                            └→ handle_document_download (1, archive)
docket_by_number ─────────────────────────────────→ parse_case_detail (2)
```

Priorities descend by depth so in-flight cases finish before new searches
start; document archive downloads ride at priority 1 (`archive=True`).

### Deduplication keys (§6)

- search requests — `SkipDeduplicationCheck()` (overlapping cap-resume
  windows are non-idempotent by design; per-case dedup filters duplicates).
- `case_detail:<docket_number>` — each case-detail fetch.
- `docket_lower_court:<county>:<lower_case_number>` — the trial-court fetch.
- `doc-<docket_number>-<document_id>-<fmt>` — each archive download
  (colon-free, since file-download keys become filenames).

### Data types

`OkDocket` (main, → CL `Docket`) with nested `OkParty`, `OkAttorney`,
`OkDocketEntry`, `OkEvent`, `OkLowerCourtCount`, and `OkLowerCourtCase`
(→ CL `OriginatingCourtInformation` / `TrialCourtData`).
