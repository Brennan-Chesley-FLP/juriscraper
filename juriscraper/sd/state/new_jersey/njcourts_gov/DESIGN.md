# New Jersey Judiciary (njcourts.gov) Scraper Design

## Site Overview

- **Base URL**: https://www.njcourts.gov
- **Requires Playwright**: No — server-rendered HTML, no bot challenge.
  All listing endpoints respond with full HTML over plain `httpx`.
- **Transport**: Drupal Views HTML pages with GET-based filter forms.
  Brief lists for each case are server-rendered inline as Bootstrap modal
  dialogs (no AJAX calls needed).

## Courts Covered

| Site URL fragment | Display Name | CourtListener ID |
|---|---|---|
| `/courts/supreme/appeals` | Supreme Court of New Jersey | `nj` |
| `/courts/appellate/argument-schedule` | NJ Superior Court Appellate Division (pending OAs) | `njsuperctappdiv` |
| `/courts/appellate/briefs-from-argued-cases` | NJ Superior Court Appellate Division (argued cases) | `njsuperctappdiv` |

## Search Capabilities

Three endpoints — two with date filters, one snapshot-only.

### `/courts/supreme/appeals` — SCOTNJ pending **and** decided

GET form on `/courts/supreme/appeals` with these query params:
- `filter_by` — one of: `Posted`, `Argued`, `Reargued`, `Decided`,
  `Certification Granted`, `Leave to Appeal Granted`, `Not Argued`, `Not Decided`.
  Filters by which event date is checked against the date range.
- `start` — ISO date `YYYY-MM-DD`
- `end` — ISO date `YYYY-MM-DD`
- `search` — free-text caption / docket search
- `page` — 0-indexed page (page 0 = no `page` param; page 1 → second page)

The same page mixes pending and decided cases, sorted newest-to-oldest.
Each row exposes one or more event dates (Posted / Petition for review
granted / Certification Granted / Leave to Appeal Granted / Argued /
Reargued / Decided by Order / Opinion Filed / Amicus Motions and Briefs
Due). 20 rows per page. Without filters: 951 items / 48 pages today.

### `/courts/appellate/argument-schedule` — SCAD pending oral arguments

**Snapshot-only.** No date filter; the page lists upcoming argument days
(typically two to four weeks ahead) grouped by date and location. No
pagination, no historical access. Treated as a dateless `@entry`.

### `/courts/appellate/briefs-from-argued-cases` — SCAD already-argued

GET form on `/courts/appellate/briefs-from-argued-cases` with these
query params:
- `search`
- `field_argued_dates_value[min]` — ISO date
- `field_argued_dates_value[max]` — ISO date
- `page` — 0-indexed

Each row carries one event: `Argued: <date>`. 20 rows per page.
Without filters: 1,057 items / 53 pages today.

**Recommended approach**: date-based search for both SCOTNJ and SCAD-argued
listings; dateless `@entry` for SCAD argument-schedule. Newest-first
walking is unnecessary because the date range is honoured server-side.

## Docket Number Formats

| Court | Pattern | Example | Notes |
|---|---|---|---|
| SCOTNJ | `A-NN-YY` (or `A-NN/MM/PP-YY` for consolidated) | `A-40-25`, `A-33/34/35-25` | The trailing `-YY` is the term year. |
| SCOTNJ (alt) | `S-NN/MM-YY` | `S-73/74-25` | Used for some procedural matters. |
| SCAD | `A-NNNN-YY` | `A-1602-24`, `A-2596-24` | Four-digit sequential per term year. |
| SCOTNJ-only sidecar | `(NNNNNN)` | `(091434)` | Internal CMS id appended to caption. |

SCOTNJ rows commonly include a "Read Appellate Opinion" link pointing at
the originating SCAD docket — that link is the cross-reference between
the two courts. SCAD opinion PDFs live under
`/system/files/court-opinions/{YYYY}/{slug}.pdf`; SCOTNJ briefs and
Supreme Court opinions live under `/system/files/court-opinions/{YYYY}/`
or `/system/files/cases/briefs/`.

## Data Available

### SCOTNJ Docket (`/courts/supreme/appeals` row)
- `docket_id` — `A-40-25`, `A-33/34/35-25`, `S-73/74-25`, etc.
- `case_name` — caption inside `<u>...</u>`
- `cms_id` — bare digits in the trailing parenthetical (e.g. `091434`)
- `appellate_opinion_url` — "Read Appellate Opinion" link target (the
  SCAD opinion that's now under SCOTNJ review). Sometimes labelled
  "Opinion {N}" for non-A-series matters.
- `appellate_docket_id` — the SCAD docket cited by that link's text
- `question_presented` — the issue paragraph (plain text)
- Event list (each event keyed by name): `Posted`, `Argued`, `Reargued`,
  `Petition for review granted`, `Certification Granted`,
  `Leave to Appeal Granted`, `Decided by Order`, `Opinion Filed`,
  `Amicus Motions and Briefs Due`, `Not Argued`, `Not Decided`.
- Briefs list: 0-N PDF links from the modal at `#{node_id}-case-briefs`.
  Brief filenames follow `a_NN_YY_<doctype>.pdf`. The modal title may
  read `… Case Document(s) - Briefs are sealed` for protected matters.

### SCAD Pending OA (`/courts/appellate/argument-schedule` row)
- `docket_id` — `A-2596-24`
- `case_name` — text after the bold docket id
- `argument_date` — derived from the enclosing `view-grouping-header`
  date heading
- `argument_location` — preceding `secondary-header` span
  (e.g. `Trenton 5th Floor`, `Newark`, `Virtual OA`, `Virtual OA 2`)
- Optional briefs PDF link (single PDF per case at
  `/system/files/cases/briefs/aNNNN-YYbriefs.pdf`)
- `(RECORD IMPOUNDED)` appears in the caption text when public access
  is denied — captured into `missing_entries_reason`.

### SCAD Argued Case (`/courts/appellate/briefs-from-argued-cases` row)
- `docket_id` — `A-1667-24`
- `case_name`
- `argument_date` — listed as `Argued: <date>`
- Briefs PDF link from modal (1 PDF per case)
- Modal title reads `Briefs are sealed` for sealed cases.

## Document Downloads

Four flavours of document live on these pages:

- **SCAD opinions** (referenced by SCOTNJ rows):
  `/system/files/court-opinions/{YYYY}/aNNNN-YY[redacted].pdf`
- **SCOTNJ orders & briefs**:
  `/system/files/cases/briefs/a_NN_YY_<doctype>.pdf`
- **SCAD argued-case briefs**:
  `/system/files/cases/briefs/aNNNN-YYbriefs.pdf`
- **SCOTNJ oral-argument media** (per-row, post-argument):
  `https://library.njcourts.gov/watch/supreme-court/{YYYY}/{MM}/{slug}.mp4`
  with a sibling `.mp3` audio file. The video is exposed via an "Oral
  Argument Video for {docket_id}" anchor that opens a Bootstrap modal
  containing a `<video><source src=…mp4>` and an `<a href=…mp3>`.

Each file is followed via `archive=True` and emitted as an `NJDocument`,
with `expected_type` set to ``pdf`` / ``mp4`` / ``mp3`` accordingly.

## Oral Arguments — Video Coverage

Inline per-docket video / audio is captured on the
`/courts/supreme/appeals` page itself for any SCOTNJ matter that has
been argued. The separate webcast archive at
`/courts/supreme/supreme-court-webcast/recent-arguments` carries the
same media for a rolling 30-day window and is therefore strictly
redundant with the per-row capture.

SCAD oral arguments are not video-archived. The
`/courts/appellate/appellate-livestreams` page renders a
"View Livestream" button only while a session is active — no archival
video survives the live broadcast.

## Bot Protection Notes

None observed. All endpoints serve full HTML to plain `curl` /
`httpx` requests. No CSRF tokens are required for the GET filter forms.

## Known Gaps

- The SCAD argument-schedule snapshot covers only the next ~2 weeks of
  upcoming arguments. Historical SCAD oral-argument metadata is
  unrecoverable from public pages — the only retrospective record is
  the briefs-from-argued-cases listing (which has the argued date but
  not the location).
- The SCAD pages do not surface oral-argument media for argued cases.
  Live SCAD argument streams are not archived publicly.

## Scraper Architecture

### Entry Points

- `get_scotnj_dockets_by_date(date_range)` — paginated walk of
  `/courts/supreme/appeals?filter_by=Posted&start=&end=&page=`. Yields
  `NJDocket` per row plus `Request(archive=True)` per brief / opinion.
- `get_scad_argued_dockets_by_date(date_range)` — paginated walk of
  `/courts/appellate/briefs-from-argued-cases` filtered on argued date.
  Yields `NJDocket` per row plus `Request(archive=True)` per brief PDF.
- `get_scad_argument_schedule()` — dateless single-GET parse of
  `/courts/appellate/argument-schedule`. Yields `NJDocket` per case in
  every upcoming sitting.

All three entry points share one `parse_listing_page` step for the
two paginated sources and one `parse_argument_schedule` step for the
snapshot source.

### Step Functions

```
get_scotnj_dockets_by_date          → parse_scotnj_listing
                                       → handle_brief_download (per PDF)
get_scad_argued_dockets_by_date     → parse_scad_argued_listing
                                       → handle_brief_download (per PDF)
get_scad_argument_schedule          → parse_argument_schedule
                                       → handle_brief_download (per PDF)
```

Each `parse_*_listing` paginates by yielding the next-page `Request`
with `SkipDeduplicationCheck()` whenever a "Next page" link is found.

### Models

- `NJDocket` — main type. One per `(court_id, docket_id)`. Includes
  `events: list[NJDocketEntry]`, `documents: list[NJDocument]`, and
  `missing_entries_reason: str | None`.
- `NJDocketEntry` — one event row from the right-hand event list (or
  the argument-schedule sitting), modelled as a docket entry.
- `NJDocument` — emitted from `handle_brief_download`; a downloaded
  brief / opinion PDF.
