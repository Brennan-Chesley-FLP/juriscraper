# New Jersey Judiciary (njcourts.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts: `nj` (Supreme Court of NJ, SCOTNJ) and `njsuperctappdiv`
> (Superior Court Appellate Division, SCAD). Plain-HTTP Drupal Views site
> with no JS challenge or CSRF gate (`driver_requirements = []`). HTML
> extraction lives in the `parsers/` package (§9: `ListingParser` for the
> two row-based listings, `ArgumentScheduleParser` for the snapshot); the
> steps keep navigation (the document download fan-out and the pager
> follow). Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md):
> `court` (not `court_id`), `docket_number` (not `docket_id`), `date_*`
> date naming, `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://www.njcourts.gov`
- **Backend**: Drupal Views HTML pages with GET-based filter forms. Brief
  lists for each case are server-rendered inline as Bootstrap modal
  dialogs (no AJAX calls needed).
- **Requires Playwright**: No — server-rendered HTML, no bot challenge.

## Courts Covered

| Site URL fragment | Display Name | CourtListener ID |
|---|---|---|
| `/courts/supreme/appeals` | Supreme Court of New Jersey | `nj` |
| `/courts/appellate/argument-schedule` | NJ Superior Court Appellate Division (pending OAs) | `njsuperctappdiv` |
| `/courts/appellate/briefs-from-argued-cases` | NJ Superior Court Appellate Division (argued cases) | `njsuperctappdiv` |

## Search Capabilities

Three endpoints — two with date filters, one snapshot-only.

### `/courts/supreme/appeals` — SCOTNJ pending **and** decided

GET form with these query params:
- `filter_by` — one of: `Posted`, `Argued`, `Reargued`, `Decided`,
  `Certification Granted`, `Leave to Appeal Granted`, `Not Argued`,
  `Not Decided`. Selects which event date is checked against the range.
  The scraper pins `filter_by=Posted` so the `DateRange` has a stable
  meaning across runs.
- `start` / `end` — ISO date `YYYY-MM-DD`.
- `search` — free-text caption / docket search (unused).
- `page` — 0-indexed page (page 0 omits the param).

The same page mixes pending and decided cases, newest-first. Each row
exposes one or more event dates. 20 rows per page; ~48 pages unfiltered.

### `/courts/appellate/argument-schedule` — SCAD pending oral arguments

**Snapshot-only.** No date filter, no pagination, no historical access;
lists upcoming argument days (~2 weeks ahead) grouped by date and
location. Modelled as the `dockets_by_bulk` (dateless) entry.

### `/courts/appellate/briefs-from-argued-cases` — SCAD already-argued

GET form with `field_argued_dates_value[min]` / `[max]` (ISO dates),
`search`, and `page` (0-indexed). Each row carries one `Argued: <date>`
event. 20 rows per page; ~53 pages unfiltered.

## Docket Number Formats

| Court | Pattern | Example | Notes |
|---|---|---|---|
| SCOTNJ | `A-NN-YY` (or `A-NN/MM/PP-YY` consolidated) | `A-40-25`, `A-33/34/35-25` | Trailing `-YY` is the term year. |
| SCOTNJ (alt) | `S-NN/MM-YY` | `S-73/74-25` | Some procedural matters. |
| SCAD | `A-NNNN-YY` | `A-1602-24` | Four-digit sequential per term year. |
| SCOTNJ-only sidecar | `(NNNNNN)` | `(091434)` | Internal CMS id appended to caption (`cms_id`). |

SCOTNJ rows commonly include a "Read Appellate Opinion" link pointing at
the originating SCAD docket — captured as `appellate_docket_number` +
`appellate_opinion_url`.

## Document Downloads

Four flavours, each followed via `archive=True` and emitted as
`NJDocument` with `expected_type` derived from the URL extension:

- **SCAD opinions** (referenced by SCOTNJ rows):
  `/system/files/court-opinions/{YYYY}/...pdf`
- **SCOTNJ orders & briefs** / **SCAD argued-case briefs**:
  `/system/files/cases/briefs/...pdf`
- **SCOTNJ oral-argument media** (per-row, post-argument):
  `https://library.njcourts.gov/.../{slug}.mp4` + sibling `.mp3`.

## Known Gaps

- The SCAD argument-schedule snapshot covers only the next ~2 weeks.
  Historical SCAD oral-argument metadata (location especially) is
  unrecoverable from public pages.
- SCAD oral arguments are not video-archived publicly.

## Bot Protection Notes

None observed. All endpoints serve full HTML to plain HTTP requests; no
CSRF tokens required for the GET filter forms.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|---|---|---|
| `dockets_by_posted_date(court_ids, date_range)` | `DateRange` | SCOTNJ; paginated walk filtered server-side on the `Posted` event date. |
| `dockets_by_argument_date(court_ids, date_range)` | `DateRange` | SCAD; paginated walk of argued cases filtered on the argument date. |
| `dockets_by_bulk(court_ids)` | — | SCAD upcoming-OA snapshot (single dateless GET). |

### Step functions and priorities (§5)

```
dockets_by_posted_date   → parse_scotnj_listing      (3) ─┐
dockets_by_argument_date → parse_scad_argued_listing (3) ─┼→ handle_document_download (1)
dockets_by_bulk          → parse_argument_schedule   (2) ─┘
```

Listing steps re-yield the next-page `Request` while a "Next page" pager
link is present. Document downloads use `archive=True` (auto-priority 1).

### Deduplication keys (§6)

- `scotnj_listing:<start>:<end>` / `scad_argued_listing:<start>:<end>` —
  the seed listing GET.
- `argument_schedule:snapshot` — the SCAD snapshot GET.
- `listing_page:<next_url>` — each paginated follow (stable URL).
- `<docket_number>-<filename>` — each archived document (colon-free, used
  as a filename).

### Data types

`NJDocket` (main, → CL `Docket`) with nested `NJDocketEntry` (→
`DocketEntry`) and `NJDocument` (→ `RECAPDocument`). `missing_entries_reason`,
`cms_id`, and the SCOTNJ→SCAD opinion cross-reference are folded onto the
docket.
