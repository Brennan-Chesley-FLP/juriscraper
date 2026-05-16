# West Virginia Courts (courtswv.gov) Scraper Design

## Site Overview
- **Base URL**: https://www.courtswv.gov
- **Requires Playwright**: No — pure server-rendered HTML over httpx.
- **Transport**: HTML form (Drupal Views exposed form, `GET` to the listing
  page with `combine` and year filters as query parameters).

The site is a Drupal site. The "Current Docket" page renders a Drupal
View whose results are server-rendered into a `<table>`. A jQuery
`bootstrap-table` plugin then takes the fully-rendered table and
client-side paginates / sorts it. **All rows are present in the initial
HTML**, so there is no AJAX endpoint we need to invoke. The site
*does* have a Drupal AJAX endpoint at `/views/ajax`, but it returns
the same content wrapped in JSON command envelopes — no advantage over
the canonical page URL, and it would need a `Referer` header. Skipping
it in favor of the page URL.

## Courts Covered

| Site listing | Display Name | CourtListener ID |
|---|---|---|
| `/appellate-courts/supreme-court-of-appeals/current-docket` | Supreme Court of Appeals of West Virginia | `wva` |
| `/appellate-courts/intermediate-court-of-appeals/current-docket` | Intermediate Court of Appeals of West Virginia | `wvactapp` |

## Search Capabilities

Each listing page exposes a Drupal Views exposed form with three filter
inputs (GET):

- `field_sca_docket_year_value` (SCA) / `field_ica_docket_entry_year_value`
  (ICA) — year of the docket date. Values: `All`, `2026`, `2025`, …,
  `2020`. Filters by the docket-entry date (the date the case is
  scheduled to be argued / order list released), **not** the case-number
  year.
- `field_sca_docket_argument_type_value` /
  `field_ica_docket_argument_type_value` — argument type (`All`,
  `RULE 19 ARGUMENT`, `RULE 20 ARGUMENT`, `ORDER LIST`, `ADMISSIONS` (SCA
  only), `BAKER'S CUP` (SCA only)).
- `combine` — free-text search across the visible columns. Matches
  partial docket numbers (e.g. `combine=24-331`) — useful for both whole
  and partial numeric searches. Matches inside consolidated
  case-no strings as well: `combine=23-753` returns the consolidated row
  for `23-753 & 24-320`.

The SCA listing spans years (≈1,106 rows from 2020 onward when invoked
with `field_sca_docket_year_value=All`). The ICA listing currently
holds only the in-flight docket (≈10 rows including order lists); the
ICA was created in 2022 and historical archive coverage is thin.

**Recommended approach**: HTML form date-based search. Fetch the listing
with the year filter set (or `All` for cross-year ranges), then
post-filter rows by docket date and follow each row's link to the
case-detail page. A separate by-docket-number entry uses
`combine={docket_id}` to locate the case slug, then follows the same
detail-parsing flow.

### Empty results

A search with no matching rows still returns HTTP 200; the body
contains `<div class="view-empty">No Results Found.</div>` in place of
the result table. The scraper detects no rows in the docket table and
yields nothing — no soft-404 override is needed because we don't
construct speculative URLs (we only follow links from the listing).

## Docket Number Formats

| Court | Pattern | Example |
|---|---|---|
| SCA (`wva`) | `YY-NNN` (year-suffix, 2-digit year, 3-4 digit sequence) | `24-331`, `25-145`, `23-658` |
| ICA (`wvactapp`) | `YY-ICA-NNN` | `25-ICA-280`, `25-ICA-289` |

**Consolidated cases** appear with multiple docket numbers separated by
` & ` (SCA) or ` and ` / ` & ` (ICA). The case-detail page is reachable
under a single composite URL and the listing's case-no cell shows the
joined string. The scraper splits on either separator and stores each
component in `WVDocket.consolidated_docket_numbers`, while
`WVDocket.docket_number` keeps the first (primary) number.

## Data Available

### Listing row (per case / per order list)

| Field | Value |
|---|---|
| Docket Date | `MM/DD/YYYY` — when the case sits / order list issues |
| Case No | docket number, or empty for an order-list row |
| Case Name | hyperlink to the case-detail page **OR** to a PDF (order list) |

Some rows include a YouTube webcast icon linking to the live argument
recording. Non-case rows ("ORDER LIST") have an empty Case No and a
direct `<a>` to a PDF.

### Case-Detail page (Drupal node)

URL shapes:
- `/appellate-courts/supreme-court-of-appeals/{docket_id}-{slug}` (SCA)
- `/appellate-courts/intermediate-court-of-appeals/{docket_id}` (ICA, slugged or numeric)
- `/appellate-courts/{...}/{joined-docket-id}` (consolidated)
- `/node/{nid}` (some ICA cases)

Each page renders one block per Drupal field. The block class names use
the prefix `field--name-field-{prefix}-docket-*` where `{prefix}` is
`sca` or `ica`:

| Drupal field | Meaning |
|---|---|
| `*-docket-date` | Argument / docket date (`<time datetime=...>`) |
| `*-docket-time` | Time (e.g. `01:20 pm`) |
| `*-docket-case-name` | Free-text case caption (multi-paragraph for consolidated) |
| `*-docket-case-no` | Docket number(s), joined string for consolidated |
| `*-docket-argument-type` | `RULE 19 ARGUMENT`, `RULE 20 ARGUMENT`, `ORDER LIST`, etc. |
| `*-docket-youtube-link` | YouTube live URL (oral argument webcast, with timestamp) |
| `*-docket-briefs` | List of file links — **absent entirely** for clerk-only cases |
| `*-docket-note` | Free-form HTML note (justices disqualified, "Briefs on file in the Office of the Clerk", etc.) |

### Briefs

`SCA Docket Briefs` / `ICA Docket Briefs` is a Drupal file field. Each
linked file has a relative URL under `/sites/default/pubfilesmnt/...`.
Brief filenames typically encode the docket number prefix
(`23-753 Order on Appeal.pdf`) so consolidated-case brief assignment
follows from the file name. Briefs are *not* nested on `WVDocket` —
the scraper schedules an `archive=True` request per brief link and
emits a top-level `WVBrief` once the PDF is on disk. Consumers join
briefs back to their parent docket on `docket_number`.

### Clerk-only briefs flag

Some cases publish no PDFs — the briefs block is absent and the docket
note contains the literal text "Briefs on file in the Office of the
Clerk." (occasionally combined with disqualification language). The
scraper sets `WVDocket.clerk_has_briefs = True` whenever the docket
note matches `(?i)briefs.*on file.*clerk` or `(?i)briefs.*filed with.*clerk`.

### Order Lists

Order lists appear as their own rows in the listing, with an empty
`field-{prefix}-docket-case-no` column and a direct PDF anchor in the
case-name column. They have **no detail page** — the listing's docket
date is the release date, and the PDF is the canonical artifact.

For each order-list row the scraper schedules an `archive=True`
request to download the PDF; a single `WVOrderListPDF` record is
emitted from the archive callback with `court_id`, `release_date`,
`download_url`, `label`, `source_url`, and `local_path`.

A dedicated *Archived Order Lists* page exists at
`/appellate-courts/{court}/order-lists`, but it is a strict subset of
what the main listing already returns when filtered by `argument_type =
ORDER LIST`. Skipping the dedicated page keeps the scraper simple.

## Email Notifications

Not available on these pages.

## Oral Arguments Calendar

The site does have per-month calendar pages at
`/appellate-courts/{court}/current-docket/{month-name}` (rendering the
same docket rows as the listing, grouped by date). These don't give us
anything the year-filtered listing doesn't already have, so we don't
add a calendar entry point. Oral-argument webcast metadata (YouTube URL
+ timestamp) is captured as part of `WVDocket`.

## Bot Protection Notes

None observed. Direct curl returns the same HTML as the browser; no
session cookies, captcha, CSRF, or `Referer` requirement. Pure GET.
Even the suggested Drupal AJAX endpoint is reachable without Playwright
— but we don't use it.

## Known Gaps

- ICA archived dockets prior to 2022 are sparse / unavailable on the
  site itself; we surface what the site exposes and no more.
- A handful of ICA listing rows link to a synthetic "month aggregator"
  page (e.g. `/appellate-courts/intermediate-court-of-appeals/04292026`)
  rather than a single case detail. The scraper follows the link and
  parses whatever fields are present; if the page renders no
  `*-docket-case-no` block we skip it (it's a calendar header, not a
  case).

## Scraper Architecture

### Entry Points

| Entry | Param | Purpose |
|---|---|---|
| `get_sca_dockets_by_date` | `DateRange` | Fetch the SCA listing for the year(s) covering the range, follow each in-window case detail link, yield `WVDocket` + briefs + order lists |
| `get_ica_dockets_by_date` | `DateRange` | Same, ICA |
| `fetch_sca_docket_by_number` | `str` | Use `combine=` to find the SCA case slug, then parse it |
| `fetch_ica_docket_by_number` | `str` | Same, ICA |

### Step Functions

```
{sca,ica}_get_dockets_by_date
        │
        ▼
parse_listing
        │
        ├── for each case row → Request → parse_case_detail
        │                                   │
        │                                   ├── ParsedData(WVDocket)
        │                                   └── for each brief link →
        │                                          archive Request → handle_brief_download
        │                                                                │
        │                                                                ▼
        │                                                          ParsedData(WVBrief)
        │
        └── for each order-list row →
                archive Request → handle_orderlist_download
                                       │
                                       ▼
                                  ParsedData(WVOrderListPDF)
```

`fetch_*_docket_by_number` reuses `parse_listing` (so consolidated cases
resolve via the same row-following code path).

### Models

- `WVDocket` — main case record (per docket-page). Does not nest
  briefs; consumers join briefs back on `docket_number`.
- `WVBrief` — brief / order linked from a case-detail page. Emitted
  top-level after the PDF is archived, with `local_path` populated.
- `WVOrderListPDF` — order-list record with release date, PDF URL,
  label, listing source URL, and `local_path` (populated after the
  archive download completes).

### Soft-404 / Empty handling

- Empty searches return HTTP 200 with `<div class="view-empty">…` and
  no result rows. The listing parser yields nothing for those — no
  overrides needed.
- `fetch_*_docket_by_number` with a non-existent number yields no
  follow-up requests and no `ParsedData` (the run completes cleanly
  with zero records).
