# West Virginia Courts (courtswv.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts (`wva` Supreme Court of Appeals, `wvactapp` Intermediate Court
> of Appeals) on one Drupal site. Pure server-rendered HTML over plain HTTP
> (`driver_requirements = []`) — no JS challenge, captcha, session, or CSRF.
> HTML extraction lives in the `parsers/` package (§9, `ListingParser` /
> `CaseDetailParser`); steps keep navigation (per-row fan-out, PDF archive
> downloads). Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md):
> `court` (not `court_id`), `docket_number`, `date_*` naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://www.courtswv.gov`
- **Backend**: Drupal. The "Current Docket" page renders a Drupal View
  server-side into a `<table>`; a jQuery `bootstrap-table` plugin then
  paginates/sorts it client-side. **All rows are present in the initial
  HTML** — no AJAX endpoint needed. The site does expose a Drupal AJAX
  endpoint at `/views/ajax` returning the same content in JSON command
  envelopes (with a `Referer` requirement) — skipped, no advantage.
- **Requires Playwright**: No.

## Courts Covered

| Site listing | Display Name | CourtListener ID |
|---|---|---|
| `/appellate-courts/supreme-court-of-appeals/current-docket` | Supreme Court of Appeals of West Virginia | `wva` |
| `/appellate-courts/intermediate-court-of-appeals/current-docket` | Intermediate Court of Appeals of West Virginia | `wvactapp` |

## Search Capabilities

Each listing page exposes a Drupal Views exposed form with three GET filters:

- `field_sca_docket_year_value` (SCA) / `field_ica_docket_entry_year_value`
  (ICA) — year of the docket date (when the case sits / the order list
  releases), **not** the case-number year. Values: `All`, `2026`…`2020`.
- `field_sca_docket_argument_type_value` /
  `field_ica_docket_argument_type_value` — argument type (`All`,
  `RULE 19 ARGUMENT`, `RULE 20 ARGUMENT`, `ORDER LIST`, `ADMISSIONS` and
  `BAKER'S CUP` SCA-only).
- `combine` — free-text search across visible columns; matches partial and
  consolidated docket numbers (`combine=23-753` returns the consolidated row
  for `23-753 & 24-320`).

The SCA listing spans years (≈1,100 rows from 2020 with `year=All`). The
ICA (created 2022) holds only the in-flight docket (≈10 rows); historical
coverage is thin.

### Empty results

A no-match search returns HTTP 200 with `<div class="view-empty">No Results
Found.</div>` and no result table. The listing parser finds no rows and
yields nothing — no soft-404 override needed (we never construct speculative
URLs, only follow links from the listing).

## Docket Number Formats

| Court | Pattern | Example |
|---|---|---|
| SCA (`wva`) | `YY-NNN` | `24-331`, `23-658` |
| ICA (`wvactapp`) | `YY-ICA-NNN` | `25-ICA-280` |

**Consolidated cases** appear with multiple numbers separated by ` & `
(SCA) or ` and ` / ` & ` (ICA), reachable under one composite URL. The
scraper splits on either separator and stores each component in
`WVDocket.consolidated_docket_numbers`; `WVDocket.docket_number` keeps the
first (primary) number.

## Data Available

### Listing row (per case / per order list)

| Field | Value |
|---|---|
| Docket Date | `MM/DD/YYYY` — when the case sits / order list issues |
| Case No | docket number, or empty for an order-list row |
| Case Name | hyperlink to the case-detail page **OR** to a PDF (order list) |

Some rows include a YouTube webcast link. Order-list rows have empty Case No
and a direct `<a>` to a PDF.

### Case-Detail page (Drupal node)

Each page renders one block per field, classes prefixed
`field--name-field-{prefix}-docket-*` (`{prefix}` = `sca`/`ica`):

| Drupal field | Meaning |
|---|---|
| `*-docket-date` | Argument / docket date (`<time datetime=...>`) → `date_argued` |
| `*-docket-time` | Time → `argument_time` |
| `*-docket-case-name` | Case caption → `case_name` |
| `*-docket-case-no` | Docket number(s) |
| `*-docket-argument-type` | `RULE 19/20 ARGUMENT`, `ORDER LIST`, etc. |
| `*-docket-youtube-link` | YouTube webcast URL |
| `*-docket-briefs` | File-link list — **absent entirely** for clerk-only cases |
| `*-docket-note` | Free-form note (disqualifications, "Briefs on file…clerk") |

### Briefs

`SCA/ICA Docket Briefs` is a Drupal file field; linked files live under
`/sites/default/pubfilesmnt/…`. Brief filenames typically encode the docket
prefix (`23-753 Order on Appeal.pdf`) so consolidated-case brief assignment
follows from the label. Briefs are **not** nested on `WVDocket` — the scraper
schedules an `archive=True` request per link and emits a top-level `WVBrief`
once the PDF is on disk; consumers join on `docket_number`.

### Clerk-only briefs flag

Some cases publish no PDFs — the briefs block is absent and the note contains
"Briefs on file in the Office of the Clerk." The scraper sets
`WVDocket.clerk_has_briefs = True` when the note matches
`(?i)briefs.*(on file|filed).*clerk`.

### Order Lists

Order lists are their own listing rows (empty case-no, direct PDF anchor),
with **no detail page** — the listing's docket date is the release date. The
scraper schedules an `archive=True` request and emits a single
`WVOrderListPDF` from the archive callback (`court`, `release_date`,
`download_url`, `label`, `source_url`, `local_path`).

A dedicated *Archived Order Lists* page exists at
`/appellate-courts/{court}/order-lists` but is a strict subset of the main
listing filtered by `argument_type = ORDER LIST`; skipped.

## Bot Protection Notes

None observed. Direct curl returns the same HTML as the browser; no session
cookies, captcha, CSRF, or `Referer` requirement. Pure GET.

## Known Gaps

- ICA archived dockets prior to 2022 are sparse / unavailable on the site;
  we surface what the site exposes and no more.
- A handful of ICA listing rows link to a synthetic "month aggregator" page
  (e.g. `/appellate-courts/intermediate-court-of-appeals/04292026`) rather
  than a single case. `CaseDetailParser` returns `[]` when the page renders
  no `*-docket-case-no` block, and the step skips it (it's a calendar header,
  not a case).

## Scraper Architecture

### Entry points (§4)

| Entry | Params | Purpose |
|---|---|---|
| `dockets_by_argument_date(court_ids, date_range)` | `set[str]`, `DateRange` | For each court, fetch the listing for the year(s) covering the range, post-filter rows by docket date, follow in-window case rows + schedule order-list PDFs. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Use `combine=` to find the case slug in one court, then parse it. |

The searchable date is the argument/docket date, so the date entry is named
`dockets_by_argument_date` (per §4 swap rules), mapping to `WVDocket.date_argued`.

### Step functions and priorities (§5)

```
dockets_by_argument_date / docket_by_number
        │
        ▼
parse_listing (4)
        │
        ├── case row → Request → parse_case_detail (3)
        │                            ├── ParsedData(WVDocket)
        │                            └── per brief → archive Request →
        │                                   handle_brief_download (1) → WVBrief
        │
        └── order-list row → archive Request →
                   handle_orderlist_download (1) → WVOrderListPDF
```

Priorities descend by depth (4 → 3) so in-flight cases finish before new
rows start; downloads (the two archive callbacks) sit at priority 1.

### Deduplication keys (§6)

- `dockets_by_argument_date` listings use `SkipDeduplicationCheck()` — the
  per-(court, year) listing GET is idempotent but cheap, and the real dedup
  happens on `case_detail:<url>` below.
- `docket_by_number:<court>:<docket_number>` — the single-lookup listing GET.
- `case_detail:<detail_url>` — each case-detail fetch (dedups a case surfaced
  by multiple searches).
- `brief <court> <download_url>` / `orderlist <court> <download_url>` — file
  downloads; space-delimited (no colon) since the key may become a filename.

### Models

- `WVDocket` (→ CL `Docket`) — main case record per detail page; does not
  nest briefs.
- `WVBrief` (→ CL `RECAPDocument`) — brief/order PDF, emitted top-level after
  archive, joined on `docket_number`.
- `WVOrderListPDF` — order-list PDF with release date, URL, label, source,
  and `local_path`.
